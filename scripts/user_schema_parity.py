"""Pure additive user schema proposal. Does not connect to or alter a database."""

from copy import deepcopy


def candidate(schema):
    if schema.get("name") != "users" or schema.get("type") != "auth":
        raise ValueError("Expected users auth collection")
    result = deepcopy(schema)
    fields = {field["name"]: field for field in result["fields"]}
    status = fields.get("status", {})
    if status.get("type") != "select" or status.get("maxSelect", 1) != 1:
        raise ValueError("Unexpected status field; manual review required")
    values = status.get("values", [])
    if set(values) - {"active", "inactive", "pending", "suspended"}:
        raise ValueError("Unknown status values; preserve and review before migration")
    status["values"] = list(
        dict.fromkeys([*values, "active", "inactive", "pending", "suspended"])
    )
    if "is_deleted" not in fields:
        result["fields"].append(
            {"name": "is_deleted", "type": "bool", "required": False}
        )
    elif fields["is_deleted"].get("type") != "bool":
        raise ValueError("Unexpected is_deleted field type")
    return result
