from fastapi import Depends

from app.application.services.transaction_gateway import TransactionGateway
from app.interface.dependencies import (
    get_auth_context,
    get_pocketbase_client,
    get_static_pocketbase_client,
)


async def get_transaction_client(
    auth=Depends(get_auth_context),
    caller=Depends(get_pocketbase_client),
    server=Depends(get_static_pocketbase_client),
):
    return TransactionGateway(caller, server, auth)
