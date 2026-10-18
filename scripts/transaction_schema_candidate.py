"""Pure schema transformation for disposable validation before production apply."""

from copy import deepcopy

COLLECTIONS = ("orders", "order_items", "payments", "bookings", "availability")


def candidate(schema):
    result = deepcopy(schema)
    name = result["name"]
    if name not in COLLECTIONS:
        raise ValueError("Unsupported collection")
    fields = {field["name"]: field for field in result["fields"]}
    for field in ("created_at", "updated_at"):
        if field not in fields:
            result["fields"].append(
                {
                    "name": field,
                    "type": "autodate",
                    "onCreate": True,
                    "onUpdate": field == "updated_at",
                }
            )
    for field in result["fields"]:
        if field["name"] in {
            "total",
            "unit_price",
            "total_price",
            "amount",
            "is_active",
        }:
            field["required"] = False
        if field["name"] in {
            "total",
            "unit_price",
            "total_price",
            "amount",
            "quantity",
            "max_bookings",
        }:
            field["min"] = 0
        if field["name"] == "status" and name in {"orders", "bookings", "payments"}:
            values = {
                "orders": ["pending", "paid", "fulfilled", "cancelled"],
                "bookings": ["pending", "confirmed", "completed", "cancelled"],
                "payments": ["pending", "completed", "failed", "cancelled", "refunded"],
            }[name]
            # Existing text fields are preserved; changing their type is a separate migration.
            if field["type"] == "select":
                field["values"] = values
    # Evaluate all joins using one alias per parent, not independent existential joins.
    auth = '@request.auth.id != "" && @request.auth.status = "active" && @request.auth.tenant_id != ""'
    parent = '@collection.sites:parent.tenant_id.tenant_id = @request.auth.tenant_id && (@collection.sites:parent.config._nexa_lifecycle.deleted_at = null || @collection.sites:parent.config._nexa_lifecycle.deleted_at = "")'
    if name in {"order_items", "payments"}:
        parent += ' && @collection.orders:owner.order_id = order_id && @collection.orders:owner.site_id = @collection.sites:parent.site_id && @collection.orders:owner.deleted_at = ""'
    else:
        parent += " && @collection.sites:parent.site_id = site_id"
    read = f'({auth}) && ({parent}) && (@request.auth.role = "owner" || @request.auth.role = "admin" || @request.auth.role = "member")'
    if name in {"orders", "bookings"}:
        read += ' && deleted_at = ""'
    read = (
        read.replace(
            ".tenant_id = @request.auth.tenant_id",
            ".tenant_id ?= @request.auth.tenant_id",
        )
        .replace(".site_id = site_id", ".site_id ?= site_id")
        .replace(".order_id = order_id", ".order_id ?= order_id")
        .replace(".site_id = @collection", ".site_id ?= @collection")
    )
    result["listRule"] = read
    result["viewRule"] = read
    # Writes remain locked until the database invariant hook candidate is accepted.
    result["createRule"] = None
    result["updateRule"] = None
    result["deleteRule"] = None
    return result
