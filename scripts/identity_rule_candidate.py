"""Conservative direct-PocketBase rule candidate; no automatic apply path.

Account administration and site mutations require server-mediated APIs before
these locked write rules can replace the current production rules.
"""

from copy import deepcopy


def candidate(schema):
    result = deepcopy(schema)
    auth = '@request.auth.id != "" && @request.auth.status = "active" && @request.auth.tenant_id != ""'
    if schema["name"] == "users":
        read = f"({auth}) && tenant_id = @request.auth.tenant_id"
        immutable = " && ".join(
            f"@request.body.{field}:changed = false"
            for field in (
                "role",
                "tenant_id",
                "status",
                "is_superuser",
                "verified",
                "emailVisibility",
                "metadata",
            )
        )
        result.update(
            listRule=read,
            viewRule=read,
            updateRule=f"({auth}) && id = @request.auth.id && {immutable}",
            createRule=None,
            deleteRule=None,
            manageRule=None,
        )
    elif schema["name"] == "sites":
        result.update(
            listRule=f'({auth}) && tenant_id.tenant_id = @request.auth.tenant_id && (config._nexa_lifecycle.deleted_at = null || config._nexa_lifecycle.deleted_at = "")',
            createRule=None,
            updateRule=None,
            deleteRule=None,
        )
        result["viewRule"] = result["listRule"]
    else:
        raise ValueError("Only users and sites are supported")
    return result
