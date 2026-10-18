import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.transaction_ownership_preflight import (
    PUBLIC_IDS,
    REQUIRED_COLLECTIONS,
    TRANSACTIONS,
    inspect_snapshot,
)


def snapshot():
    records = {name: [] for name in REQUIRED_COLLECTIONS}
    records.update(
        {
            "tenants": [
                {"id": "tenant_record_a", "tenant_id": "tenant_public_a"},
                {"id": "tenant_record_b", "tenant_id": "tenant_public_b"},
            ],
            "users": [{"id": "user_a", "tenant_id": "tenant_public_a"}],
            "sites": [
                {
                    "id": "site_record_a",
                    "site_id": "site_a",
                    "tenant_id": "tenant_record_a",
                    "config": {},
                },
                {
                    "id": "site_record_b",
                    "site_id": "site_b",
                    "tenant_id": "tenant_record_b",
                    "config": {},
                },
            ],
            "properties": [
                {
                    "id": "property_record_a",
                    "property_id": "service_a",
                    "site_id": "site_a",
                    "type": "spa_service",
                    "status": "published",
                },
                {
                    "id": "property_record_b",
                    "property_id": "service_b",
                    "site_id": "site_b",
                    "type": "spa_service",
                    "status": "published",
                },
                {
                    "id": "legacy_record",
                    "property_id": "legacy_a",
                    "site_id": "site_a",
                    "type": "booking_submission",
                },
            ],
            "orders": [
                {
                    "id": "order_record_a",
                    "order_id": "order_a",
                    "site_id": "site_a",
                    "customer_email": "private@example.test",
                }
            ],
            "order_items": [
                {
                    "id": "item_record_a",
                    "item_id": "item_a",
                    "order_id": "order_a",
                    "property_id": "service_a",
                }
            ],
            "payments": [
                {
                    "id": "payment_record_a",
                    "payment_id": "payment_a",
                    "order_id": "order_a",
                }
            ],
            "bookings": [
                {
                    "id": "booking_record_a",
                    "booking_id": "booking_a",
                    "site_id": "site_a",
                    "property_id": "service_a",
                    "metadata": {"legacy_property_id": "legacy_a"},
                }
            ],
            "availability": [
                {
                    "id": "slot_record_a",
                    "availability_id": "slot_a",
                    "site_id": "site_a",
                    "property_id": "service_a",
                }
            ],
        }
    )
    schemas = []
    for name in TRANSACTIONS:
        fields = {PUBLIC_IDS[name], "created_at", "updated_at"}
        fields.add("order_id" if name in ("order_items", "payments") else "site_id")
        if name in ("order_items", "bookings", "availability"):
            fields.add("property_id")
        schemas.append(
            {
                "name": name,
                "fields": [{"name": field, "type": "text"} for field in sorted(fields)],
                "listRule": "@request.auth.id != ''",
                "viewRule": "@request.auth.id != ''",
            }
        )
    return {
        "collections": schemas,
        "records": records,
        "record_counts": {name: len(rows) for name, rows in records.items()},
        "complete_collections": list(REQUIRED_COLLECTIONS),
    }


def codes(data):
    return inspect_snapshot(data)["finding_counts"]


def test_resolves_public_and_record_ids_without_mutation_or_pii():
    data = snapshot()
    before = copy.deepcopy(data)
    report = inspect_snapshot(data)
    assert report["resolved_ownership_counts"] == dict.fromkeys(TRANSACTIONS, 1)
    assert data == before
    assert "private@example.test" not in json.dumps(report)
    assert report["migration_approved"] is False
    assert report["review_required"] is True


@pytest.mark.parametrize("change", ["missing", "count", "complete", "boolean_count"])
def test_rejects_partial_snapshots(change):
    data = snapshot()
    if change == "missing":
        del data["records"]["payments"]
    elif change == "count":
        data["record_counts"]["payments"] = 100
    elif change == "complete":
        data["complete_collections"].remove("payments")
    else:
        data["record_counts"]["payments"] = True
    with pytest.raises(ValueError):
        inspect_snapshot(data)


def test_does_not_confuse_tenant_public_id_with_record_relation():
    data = snapshot()
    data["records"]["sites"][0]["tenant_id"] = "tenant_public_a"
    assert "missing_or_ambiguous_tenant_relation" in codes(data)
    assert inspect_snapshot(data)["resolved_ownership_counts"]["orders"] == 0


def test_rejects_cross_site_property_in_same_tenant():
    data = snapshot()
    data["records"]["sites"][1]["tenant_id"] = "tenant_record_a"
    data["records"]["order_items"][0]["property_id"] = "service_b"
    assert "cross_site_property" in codes(data)


def test_orphan_children_and_duplicate_parent_ids_are_blocked():
    data = snapshot()
    data["records"]["payments"][0]["order_id"] = "unknown"
    data["records"]["orders"].append(
        {"id": "duplicate_order", "order_id": "order_a", "site_id": "site_b"}
    )
    data["record_counts"]["orders"] += 1
    findings = codes(data)
    assert findings["duplicate_public_id"] == 2
    assert findings["missing_or_ambiguous_orders"] == 2


def test_retained_and_deleted_parents_require_policy():
    data = snapshot()
    data["records"]["sites"][0]["config"] = {"_nexa_lifecycle": {"deleted_at": "now"}}
    data["records"]["orders"][0]["deleted_at"] = "now"
    findings = codes(data)
    assert findings["retained_parent_requires_explicit_policy"] == 3
    assert findings["deleted_order_requires_explicit_policy"] == 2


def test_backfill_marker_conflict_and_duplicate_are_blocked():
    data = snapshot()
    duplicate = copy.deepcopy(data["records"]["bookings"][0])
    duplicate.update(id="booking_record_b", booking_id="booking_b")
    data["records"]["bookings"].append(duplicate)
    data["record_counts"]["bookings"] += 1
    assert codes(data)["duplicate_legacy_marker"] == 2
    duplicate["legacy_property_id"] = "other"
    assert "conflicting_legacy_marker" in codes(data)


def test_invalid_publication_and_legacy_source_are_blocked():
    data = snapshot()
    data["records"]["properties"][0]["status"] = "draft"
    data["records"]["properties"][2]["site_id"] = "site_b"
    findings = codes(data)
    assert findings["ineligible_booking_property"] == 2
    assert findings["invalid_legacy_source"] == 1


def test_schema_rules_and_false_zero_required_fields_are_reported():
    data = snapshot()
    data["collections"][0]["fields"].append(
        {"name": "total", "type": "number", "required": True}
    )
    data["collections"][-1]["fields"].append(
        {"name": "is_active", "type": "bool", "required": True}
    )
    data["collections"][0]["createRule"] = ""
    findings = codes(data)
    assert findings["unscoped_list_rule"] == 5
    assert findings["caller_token_create_locked"] == 4
    assert findings["review_create_rule_and_hooks"] == 1
    assert findings["required_zero_or_false_sensitive_total"] == 1
    assert findings["required_zero_or_false_sensitive_is_active"] == 1


def test_reports_actual_legacy_migration_schema_gaps_without_importing_it():
    data = snapshot()
    path = Path(__file__).resolve().parents[2] / "scripts/migrate_transactional.py"
    tree = ast.parse(path.read_text())
    definitions = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "COLLECTIONS"
            for target in node.targets
        )
    )
    for schema in data["collections"]:
        schema["fields"] = [
            {"name": name, "type": kind, "required": required}
            for name, kind, required in definitions[schema["name"]]["fields"]
        ]
    findings = codes(data)
    assert findings["missing_created_at"] == 5
    assert findings["missing_updated_at"] == 5
    assert findings["unscoped_view_rule"] == 5


def test_cli_is_read_only_and_returns_blocked_status(tmp_path):
    source = tmp_path / "snapshot.json"
    raw = json.dumps(snapshot())
    source.write_text(raw)
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts/transaction_ownership_preflight.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), str(source)], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["mode"] == "offline_read_only"
    assert source.read_text() == raw
    assert list(tmp_path.iterdir()) == [source]
