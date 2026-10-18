from fastapi import Depends

from app.application.services.account_gateway import AccountGateway
from app.interface.dependencies import get_auth_context, get_static_pocketbase_client


async def get_account_management_client(
    auth=Depends(get_auth_context), server=Depends(get_static_pocketbase_client)
):
    return AccountGateway(server, auth)
