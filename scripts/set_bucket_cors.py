"""One-time migration: set CORS policy on all existing S3 buckets.

Run: python scripts/set_bucket_cors.py
"""

import asyncio
import sys

sys.path.insert(0, ".")

from app.config import get_settings
from app.infrastructure.storage.client import StorageClient

SITE_BASE_DOMAIN = "promotiem.dpdns.org"

CORS_ORIGINS = [
    f"https://{SITE_BASE_DOMAIN}",
    f"https://*.{SITE_BASE_DOMAIN}",
]

CORS_CONFIG = {
    "CORSRules": [
        {
            "AllowedOrigins": CORS_ORIGINS,
            "AllowedMethods": ["GET", "HEAD", "OPTIONS"],
            "AllowedHeaders": [
                "Authorization",
                "Content-Type",
                "Content-Length",
                "Content-Range",
                "Accept",
                "Origin",
                "x-amz-*",
            ],
            "ExposeHeaders": [
                "Content-Length",
                "Content-Type",
                "Content-Range",
            ],
            "MaxAgeSeconds": 3600,
        }
    ]
}


async def main():
    s = get_settings().storage
    client = StorageClient(
        endpoint_url=s.endpoint_url,
        public_endpoint_url=s.public_endpoint_url,
        access_key=s.access_key,
        secret_key=s.secret_key,
        region=s.region,
        presign_expiry_seconds=s.presign_expiry_seconds,
    )

    async with client._client() as s3:
        resp = await s3.list_buckets()
        buckets = [b["Name"] for b in resp.get("Buckets", [])]

    print(f"Found {len(buckets)} buckets. Setting CORS...")

    success = 0
    skipped = 0
    failed = 0

    async with client._client() as s3:
        for bucket in buckets:
            try:
                await s3.put_bucket_cors(
                    Bucket=bucket, CORSConfiguration=CORS_CONFIG
                )
                print(f"  [OK]  {bucket}")
                success += 1
            except Exception as e:
                print(f"  [ERR] {bucket}: {e}")
                failed += 1

    print(f"\nDone: {success} updated, {failed} failed")


if __name__ == "__main__":
    asyncio.run(main())
