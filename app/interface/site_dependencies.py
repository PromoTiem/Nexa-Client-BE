from fastapi import Depends, Request

from app.application.services.site_gateway import SiteGateway
from app.application.services.site_workflow_gateway import SiteWorkflowGateway
from app.interface.dependencies import (
    get_auth_context,
    get_pocketbase_client,
    get_static_pocketbase_client,
)


async def get_site_management_client(
    request: Request,
    auth=Depends(get_auth_context),
    caller=Depends(get_pocketbase_client),
    server=Depends(get_static_pocketbase_client),
):
    operation = {"POST": "create", "PATCH": "update", "DELETE": "delete"}.get(
        request.method
    )
    return SiteGateway(caller, server, auth, operation)


async def get_serve_site_client(
    auth=Depends(get_auth_context),
    caller=Depends(get_pocketbase_client),
    server=Depends(get_static_pocketbase_client),
):
    return SiteWorkflowGateway(caller, server, auth, "serve")


async def get_bucket_site_client(
    auth=Depends(get_auth_context),
    caller=Depends(get_pocketbase_client),
    server=Depends(get_static_pocketbase_client),
):
    return SiteWorkflowGateway(caller, server, auth, "bucket")
