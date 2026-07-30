from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.application.services.constants import SOFT_DELETE_FILTER
from app.infrastructure.logging import get_logger
from app.infrastructure.pocketbase.client import PocketBaseClient
from app.infrastructure.validation.field_validator import validate_fields, validate_groups

logger = get_logger("property_service")

COLLECTION = "properties"
CATEGORY_TYPE = "category"


def _dump_models(items: List[Any]) -> List[Any]:
    if items and hasattr(items[0], "model_dump"):
        return [i.model_dump(mode="python") for i in items]
    return items


class PropertyService:
    async def _check_slug_unique(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        slug: str,
        exclude_property_id: Optional[str] = None,
    ) -> None:
        """Validate slug is unique within a site (excluding soft-deleted)."""
        if not slug:
            return
        filter_parts = [
            f'site_id="{site_id}"',
            f'slug="{slug}"',
            SOFT_DELETE_FILTER,
        ]
        if exclude_property_id:
            filter_parts.append(f'property_id!="{exclude_property_id}"')
        filter_expr = " && ".join(filter_parts)
        result = await pb.list_records(
            collection=COLLECTION,
            token=token,
            filter=filter_expr,
            page=1,
            per_page=1,
        )
        if result.get("totalItems", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Slug '{slug}' already exists for this site",
            )

    async def _validate_category(
        self,
        pb: PocketBaseClient,
        token: str,
        site_id: str,
        data: Dict[str, Any],
    ) -> None:
        """Validate category-specific rules."""
        if data.get("type") != CATEGORY_TYPE:
            return

        slug = data.get("slug")
        if not slug:
            raise HTTPException(
                status_code=422,
                detail="Category must have a slug",
            )

        groups = data.get("groups", [])
        dumped_groups = [g.model_dump(mode="python") if hasattr(g, "model_dump") else g for g in groups]
        for group in dumped_groups:
            if group.get("key") == "children":
                for entry in group.get("entries", []):
                    child_id = entry.get("child_id")
                    if child_id:
                        filter_expr = f'property_id="{child_id}" && site_id="{site_id}" && {SOFT_DELETE_FILTER}'
                        result = await pb.list_records(
                            collection=COLLECTION,
                            token=token,
                            filter=filter_expr,
                            page=1,
                            per_page=1,
                        )
                        if result.get("totalItems", 0) == 0:
                            raise HTTPException(
                                status_code=422,
                                detail=f"Child category '{child_id}' not found",
                            )

    async def create_property(
        self,
        pb: PocketBaseClient,
        token: str,
        user_id: str,
        site_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        fields_data = data.get("fields", [])
        groups_data = data.get("groups", [])

        errors: List[str] = []
        errors.extend(validate_fields([f.model_dump(mode="python") if hasattr(f, "model_dump") else f for f in fields_data]))
        errors.extend(validate_groups([g.model_dump(mode="python") if hasattr(g, "model_dump") else g for g in groups_data]))
        if errors:
            raise HTTPException(
                status_code=400,
                detail=f"Validation error: {'; '.join(errors)}",
            )

        slug = data.get("slug")
        if slug:
            await self._check_slug_unique(pb, token, site_id, slug)

        await self._validate_category(pb, token, site_id, data)

        now = datetime.now(timezone.utc).isoformat()
        published_at = now if data.get("status") == "published" else None

        record = await pb.create_record(
            collection=COLLECTION,
            data={
                "property_id": data["property_id"],
                "site_id": site_id,
                "type": data.get("type"),
                "subtype": data.get("subtype"),
                "name": data["name"],
                "slug": slug,
                "status": data.get("status", "draft"),
                "excerpt": data.get("excerpt"),
                "featured_image": data.get("featured_image"),
                "seo": data.get("seo"),
                "published_at": published_at,
                "fields": [f.model_dump(mode="python") if hasattr(f, "model_dump") else f for f in fields_data],
                "groups": [g.model_dump(mode="python") if hasattr(g, "model_dump") else g for g in groups_data],
                "metadata": data.get("metadata"),
                "ordering": data.get("ordering", 0),
            },
            token=token,
            user_id=user_id,
        )
        return record

    async def update_property(
        self,
        pb: PocketBaseClient,
        token: str,
        user_id: str,
        record: Dict[str, Any],
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        if "fields" in updates and updates["fields"] is not None:
            fields_data = updates["fields"]
            dumped = _dump_models(fields_data)
            errors = validate_fields(dumped)
            if errors:
                raise HTTPException(
                    status_code=400,
                    detail=f"Validation error: {'; '.join(errors)}",
                )
            updates["fields"] = dumped

        if "groups" in updates and updates["groups"] is not None:
            groups_data = updates["groups"]
            dumped = _dump_models(groups_data)
            errors = validate_groups(dumped)
            if errors:
                raise HTTPException(
                    status_code=400,
                    detail=f"Validation error: {'; '.join(errors)}",
                )
            updates["groups"] = dumped

        if "slug" in updates and updates["slug"]:
            site_id = record.get("site_id")
            property_id = record.get("property_id")
            await self._check_slug_unique(pb, token, site_id, updates["slug"], exclude_property_id=property_id)

        if record.get("type") == CATEGORY_TYPE and "groups" in updates:
            site_id = record.get("site_id")
            await self._validate_category(pb, token, site_id, {**record, **updates})

        if "status" in updates and updates["status"] == "published" and record.get("status") != "published":
            updates["published_at"] = datetime.now(timezone.utc).isoformat()

        if not updates:
            return record

        result = await pb.update_record(
            collection=COLLECTION,
            record_id=record["id"],
            data=updates,
            token=token,
            user_id=user_id,
        )
        return result

    async def soft_delete_property(
        self,
        pb: PocketBaseClient,
        token: str,
        user_id: str,
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return await pb.update_record(
            collection=COLLECTION,
            record_id=record["id"],
            data={"deleted_at": now},
            token=token,
            user_id=user_id,
        )
