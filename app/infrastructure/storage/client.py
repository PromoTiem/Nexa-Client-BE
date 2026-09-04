import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import aioboto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
)
from fastapi import HTTPException

from app.infrastructure.logging import get_logger
from app.infrastructure.retry_utils import execute_with_retry, make_retry_decorator

logger = get_logger("storage")

_CONN_ERRORS = (EndpointConnectionError, BotoCoreError)
_STORAGE_ERRORS = (*_CONN_ERRORS, ClientError)
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename(filename: str) -> str:
    base = (filename or "").replace("\\", "/").split("/")[-1].strip()
    cleaned = _UNSAFE_CHARS.sub("_", base)
    return cleaned or "file"


def _build_key(site_id: str, original_filename: str) -> str:
    date = datetime.now(UTC).strftime("%Y%m%d")
    unique = uuid.uuid4().hex[:8]
    safe = _sanitize_filename(original_filename)
    return f"{site_id}/{date}_{unique}_{safe}"


def _expires_at(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _raise_storage_error(op: str, exc: Exception, **extra: Any) -> None:
    logger.warning(
        "storage operation failed",
        extra={"operation": op, "error": str(exc), **extra},
    )
    raise HTTPException(status_code=503, detail="Storage service error") from exc


class StorageClient:
    def __init__(
        self,
        endpoint_url: str,
        public_endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str,
        presign_expiry_seconds: int,
        max_retries: int = 3,
        retry_backoff: float = 0.5,
        session: Optional["aioboto3.Session"] = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._public_endpoint_url = public_endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._presign_expiry_seconds = presign_expiry_seconds
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._session = session or aioboto3.Session()
        self._config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

    def _client(self, *, public: bool = False):
        return self._session.client(
            "s3",
            endpoint_url=(self._public_endpoint_url if public else self._endpoint_url),
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=self._config,
        )

    def _make_retry(self, op: str) -> Callable:
        return make_retry_decorator(
            max_retries=self._max_retries,
            backoff=self._retry_backoff,
            max_jitter=10,
            service="storage",
            retry_exceptions=_CONN_ERRORS,
            retry_on_result=False,
            extra_context=f"storage:{op}",
        )

    async def _execute_with_retry(self, op: str, fn: Callable) -> Any:
        return await execute_with_retry(self._make_retry(op), fn)

    async def presign_put(
        self, bucket: str, site_id: str, filename: str, content_type: str
    ) -> dict[str, Any]:
        key = _build_key(site_id, filename)

        async def _do_presign() -> str:
            async with self._client(public=True) as s3:
                return await s3.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": bucket,
                        "Key": key,
                        "ContentType": content_type,
                    },
                    ExpiresIn=self._presign_expiry_seconds,
                )

        try:
            upload_url = await self._execute_with_retry("presign_put", _do_presign)
        except _STORAGE_ERRORS as exc:
            _raise_storage_error("presign_put", exc, key=key)

        return {
            "bucket": bucket,
            "key": key,
            "upload_url": upload_url,
            "expires_at": _expires_at(self._presign_expiry_seconds),
        }

    async def presign_get(self, bucket: str, key: str) -> dict[str, Any]:
        async def _do_presign() -> str:
            async with self._client(public=True) as s3:
                return await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=self._presign_expiry_seconds,
                )

        try:
            download_url = await self._execute_with_retry("presign_get", _do_presign)
        except _STORAGE_ERRORS as exc:
            _raise_storage_error("presign_get", exc, key=key)

        return {
            "download_url": download_url,
            "expires_at": _expires_at(self._presign_expiry_seconds),
        }

    def get_public_url(self, bucket: str, key: str) -> str:
        return f"{self._public_endpoint_url}/{bucket}/{key}"

    async def set_bucket_public_policy(self, bucket: str) -> None:
        policy = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{bucket}/*"],
                    }
                ],
            }
        )

        async def _do_put_policy() -> None:
            async with self._client() as s3:
                await s3.put_bucket_policy(Bucket=bucket, Policy=policy)

        try:
            await self._execute_with_retry("set_bucket_public_policy", _do_put_policy)
        except _STORAGE_ERRORS as exc:
            _raise_storage_error("set_bucket_public_policy", exc, bucket=bucket)

    async def head(self, bucket: str, key: str) -> dict[str, Any]:
        async def _do_head() -> dict[str, Any]:
            async with self._client() as s3:
                return await s3.head_object(Bucket=bucket, Key=key)

        try:
            resp = await self._execute_with_retry("head", _do_head)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return {"exists": False, "size": None, "content_type": None}
            _raise_storage_error("head", exc, key=key)
        except _CONN_ERRORS as exc:
            _raise_storage_error("head", exc, key=key)

        return {
            "exists": True,
            "size": resp["ContentLength"],
            "content_type": resp.get("ContentType"),
        }

    async def get_object(self, bucket: str, key: str) -> bytes:
        async def _do_get() -> bytes:
            async with self._client() as s3:
                resp = await s3.get_object(Bucket=bucket, Key=key)
                return await resp["Body"].read()

        try:
            return await self._execute_with_retry("get_object", _do_get)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                raise HTTPException(
                    status_code=404,
                    detail=f"Object not found: {key}",
                ) from exc
            _raise_storage_error("get_object", exc, key=key)
        except _CONN_ERRORS as exc:
            _raise_storage_error("get_object", exc, key=key)

    async def put_object(self, bucket: str, key: str, data: bytes) -> None:
        async def _do_put() -> None:
            async with self._client() as s3:
                await s3.put_object(Bucket=bucket, Key=key, Body=data)

        try:
            await self._execute_with_retry("put_object", _do_put)
        except _STORAGE_ERRORS as exc:
            _raise_storage_error("put_object", exc, key=key)

    async def list_objects(self, bucket: str, prefix: str) -> list[str]:
        async def _do_list() -> list[str]:
            keys: list[str] = []
            async with self._client() as s3:
                try:
                    paginator = s3.get_paginator("list_objects_v2")
                    async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                        for obj in page.get("Contents", []):
                            keys.append(obj["Key"])
                except (ClientError, BotoCoreError) as exc:
                    logger.warning(
                        "paginator failed, falling back to list_objects",
                        extra={"bucket": bucket, "prefix": prefix, "error": str(exc)},
                    )
                    resp = await s3.list_objects(Bucket=bucket, Prefix=prefix)
                    for obj in resp.get("Contents", []):
                        keys.append(obj["Key"])

            return keys

        try:
            return await self._execute_with_retry("list_objects", _do_list)
        except _STORAGE_ERRORS as exc:
            _raise_storage_error("list_objects", exc, prefix=prefix)

    async def delete_object(self, bucket: str, key: str) -> None:
        async def _do_delete() -> None:
            async with self._client() as s3:
                await s3.delete_object(Bucket=bucket, Key=key)

        try:
            await self._execute_with_retry("delete_object", _do_delete)
        except _STORAGE_ERRORS as exc:
            _raise_storage_error("delete_object", exc, key=key)

    async def create_bucket(self, bucket: str) -> None:
        async def _do_create() -> None:
            async with self._client() as s3:
                await s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": self._region}
                    if self._region != "us-east-1"
                    else {},
                )

        try:
            await self._execute_with_retry("create_bucket", _do_create)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                return
            _raise_storage_error("create_bucket", exc, bucket=bucket)
        except _CONN_ERRORS as exc:
            _raise_storage_error("create_bucket", exc, bucket=bucket)

    async def bucket_exists(self, bucket: str) -> bool:
        async def _do_head() -> bool:
            async with self._client() as s3:
                try:
                    await s3.head_bucket(Bucket=bucket)
                    return True
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code in ("404", "NoSuchBucket", "NotFound"):
                        return False
                    raise

        try:
            return await self._execute_with_retry("bucket_exists", _do_head)
        except _STORAGE_ERRORS as exc:
            _raise_storage_error("bucket_exists", exc, bucket=bucket)

    async def delete_bucket(self, bucket: str) -> None:
        async def _do_delete() -> None:
            async with self._client() as s3:
                await s3.delete_bucket(Bucket=bucket)

        try:
            await self._execute_with_retry("delete_bucket", _do_delete)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "NoSuchBucket":
                return
            _raise_storage_error("delete_bucket", exc, bucket=bucket)
        except _CONN_ERRORS as exc:
            _raise_storage_error("delete_bucket", exc, bucket=bucket)
