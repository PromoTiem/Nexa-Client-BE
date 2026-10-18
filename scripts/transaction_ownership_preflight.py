"""Offline preflight for #137; consumes an explicit, complete JSON snapshot.

No settings, credentials, network client, migration, or write path is loaded.
Exit 0 means the snapshot was inspected, not that a migration is approved.
Exit 2 means data/schema blockers remain; exit 1 means invalid input.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TRANSACTIONS = ("orders", "order_items", "payments", "bookings", "availability")
PUBLIC_IDS = {
    "tenants": "tenant_id",
    "sites": "site_id",
    "properties": "property_id",
    "orders": "order_id",
    "order_items": "item_id",
    "payments": "payment_id",
    "bookings": "booking_id",
    "availability": "availability_id",
}
REQUIRED_COLLECTIONS = ("users", *PUBLIC_IDS)


def inspect_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Report blockers without returning customer data or modifying input."""
    if not isinstance(snapshot, dict):
        raise ValueError("Snapshot must be an object")
    records = snapshot.get("records")
    schemas = snapshot.get("collections")
    counts = snapshot.get("record_counts")
    if (
        not isinstance(records, dict)
        or not isinstance(schemas, list)
        or not isinstance(counts, dict)
    ):
        raise ValueError("collections, records, and record_counts are required")
    if any(not isinstance(schema, dict) for schema in schemas):
        raise ValueError("Collection definitions must be objects")
    complete = snapshot.get("complete_collections", [])
    if not isinstance(complete, list) or any(
        not isinstance(name, str) for name in complete
    ):
        raise ValueError("complete_collections must be an array of collection names")
    for name in REQUIRED_COLLECTIONS:
        rows = records.get(name)
        if (
            name not in complete
            or not isinstance(rows, list)
            or type(counts.get(name)) is not int
            or counts.get(name) != len(rows)
        ):
            raise ValueError(
                f"Complete record inventory and exact count required: {name}"
            )
        if any(
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row["id"]
            for row in rows
        ):
            raise ValueError(f"Every {name} record must have a nonempty string id")
    findings = []

    def issue(code: str, collection: str, record_id: str | None = None) -> None:
        finding = {"code": code, "collection": collection}
        if record_id is not None:
            finding["record_id"] = record_id
        findings.append(finding)

    indexes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, field in PUBLIC_IDS.items():
        index = defaultdict(list)
        for row in records[name]:
            value = row.get(field)
            if not isinstance(value, str) or not value:
                issue("missing_public_id", name, row["id"])
                continue
            index[value].append(row)
        for rows in index.values():
            if len(rows) > 1:
                for row in rows:
                    issue("duplicate_public_id", name, row["id"])
        indexes[name] = index
    record_indexes = {}
    for name in REQUIRED_COLLECTIONS:
        index = defaultdict(list)
        for row in records[name]:
            index[row["id"]].append(row)
        for rows in index.values():
            if len(rows) > 1:
                issue("duplicate_record_id", name, rows[0]["id"])
        record_indexes[name] = index

    def public_parent(name, value, child, record_id):
        matches = indexes[name].get(value, []) if isinstance(value, str) else []
        if len(matches) != 1:
            issue("missing_or_ambiguous_" + name, child, record_id)
            return None
        return matches[0]

    def tenant_for_site(site):
        value = site.get("tenant_id")
        matches = (
            record_indexes["tenants"].get(value, []) if isinstance(value, str) else []
        )
        if len(matches) != 1:
            issue("missing_or_ambiguous_tenant_relation", "sites", site["id"])
            return None
        return matches[0]

    for user in records["users"]:
        public_parent("tenants", user.get("tenant_id"), "users", user["id"])
    for site in records["sites"]:
        tenant_for_site(site)

    owners = {name: {} for name in TRANSACTIONS}
    for name in ("orders", "bookings", "availability"):
        for row in records[name]:
            site = public_parent("sites", row.get("site_id"), name, row["id"])
            if site is None:
                continue
            tenant = tenant_for_site(site)
            if tenant is not None:
                owners[name][row["id"]] = (site, tenant)
            config = site.get("config") or {}
            lifecycle = (
                config.get("_nexa_lifecycle", {}) if isinstance(config, dict) else None
            )
            if not isinstance(lifecycle, dict):
                issue("invalid_parent_lifecycle", name, row["id"])
            elif (
                lifecycle.get("deleted_at")
                or lifecycle.get("cleanup_status") == "retained"
            ):
                issue("retained_parent_requires_explicit_policy", name, row["id"])

    for name in ("order_items", "payments"):
        for row in records[name]:
            order = public_parent("orders", row.get("order_id"), name, row["id"])
            if order is None:
                continue
            owner = owners["orders"].get(order["id"])
            if owner is not None:
                owners[name][row["id"]] = owner
            else:
                issue("unresolved_order_ownership", name, row["id"])
            if order.get("deleted_at"):
                issue("deleted_order_requires_explicit_policy", name, row["id"])

    for name in ("order_items", "bookings", "availability"):
        for row in records[name]:
            prop = public_parent("properties", row.get("property_id"), name, row["id"])
            owner = owners[name].get(row["id"])
            if prop is None or owner is None:
                continue
            if prop.get("site_id") != owner[0].get("site_id"):
                issue("cross_site_property", name, row["id"])
            if prop.get("deleted_at"):
                issue("deleted_property_requires_explicit_policy", name, row["id"])
            if name in ("bookings", "availability") and (
                prop.get("type") != "spa_service" or prop.get("status") != "published"
            ):
                issue("ineligible_booking_property", name, row["id"])

    markers = defaultdict(list)
    for row in records["bookings"]:
        metadata = row.get("metadata") or {}
        if not isinstance(metadata, dict):
            issue("invalid_booking_metadata", "bookings", row["id"])
            continue
        nested = metadata.get("legacy_property_id")
        top = row.get("legacy_property_id")
        if nested and top and nested != top:
            issue("conflicting_legacy_marker", "bookings", row["id"])
        marker = top or nested
        if marker:
            if not isinstance(marker, str):
                issue("invalid_legacy_marker", "bookings", row["id"])
                continue
            # Public property IDs are globally unique; scope cannot hide duplicates.
            markers[marker].append(row)
            source = public_parent("properties", marker, "bookings", row["id"])
            if source and (
                source.get("type") != "booking_submission"
                or source.get("site_id") != row.get("site_id")
            ):
                issue("invalid_legacy_source", "bookings", row["id"])
    for rows in markers.values():
        if len(rows) > 1:
            for row in rows:
                issue("duplicate_legacy_marker", "bookings", row["id"])

    for name in TRANSACTIONS:
        definitions = [schema for schema in schemas if schema.get("name") == name]
        if len(definitions) != 1:
            issue("missing_or_duplicate_schema", name)
            continue
        schema = definitions[0]
        fields = schema.get("fields")
        if not isinstance(fields, list) or any(
            not isinstance(field, dict) for field in fields
        ):
            raise ValueError(f"Invalid fields for {name}")
        by_name = {field.get("name"): field for field in fields}
        if len(by_name) != len(fields):
            issue("duplicate_field_definition", name)
        expected_text = [PUBLIC_IDS[name]]
        expected_text.append(
            "order_id" if name in ("order_items", "payments") else "site_id"
        )
        if name in ("order_items", "bookings", "availability"):
            expected_text.append("property_id")
        for field in expected_text:
            if by_name.get(field, {}).get("type") != "text":
                issue("unexpected_reference_type_" + field, name)
        for field in ("created_at", "updated_at"):
            if field not in by_name:
                issue("missing_" + field, name)
        for field in ("total", "unit_price", "total_price", "amount", "is_active"):
            if by_name.get(field, {}).get("required"):
                issue("required_zero_or_false_sensitive_" + field, name)
        for action in ("list", "view"):
            rule = schema.get(action + "Rule")
            normalized = (
                re.sub(r"\s+", "", rule).replace('"', "'")
                if isinstance(rule, str)
                else None
            )
            if normalized in ("", "@request.auth.id!=''"):
                issue("unscoped_" + action + "_rule", name)
            elif rule is None:
                issue("locked_" + action + "_rule", name)
            else:
                issue("review_" + action + "_rule", name)
        for action in ("create", "update", "delete"):
            if schema.get(action + "Rule") is None:
                # Hard deletes should remain locked; the caller-token create/update paths cannot.
                if action != "delete":
                    issue("caller_token_" + action + "_locked", name)
            else:
                issue("review_" + action + "_rule_and_hooks", name)

    return {
        "mode": "offline_read_only",
        "migration_approved": False,
        "review_required": True,
        "counts": {name: len(records[name]) for name in REQUIRED_COLLECTIONS},
        "resolved_ownership_counts": {name: len(rows) for name, rows in owners.items()},
        "finding_counts": dict(
            sorted(Counter(item["code"] for item in findings).items())
        ),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Complete offline JSON snapshot")
    args = parser.parse_args()
    try:
        report = inspect_snapshot(json.loads(args.snapshot.read_text()))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f"Invalid snapshot: {type(error).__name__}\n")
    print(json.dumps(report, indent=2))
    return 2 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
