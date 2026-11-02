# ruff: noqa: N815
from pydantic import BaseModel, ConfigDict


class MomoCreatePaymentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    partnerCode: str
    partnerName: str = ""
    storeId: str = ""
    requestId: str
    amount: int
    orderId: str
    orderInfo: str
    redirectUrl: str
    ipnUrl: str
    lang: str = "vi"
    extraData: str = ""
    requestType: str = "captureWallet"
    autoCapture: bool = True
    signature: str = ""


class MomoCreatePaymentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    partnerCode: str
    orderId: str
    requestId: str
    amount: int
    responseTime: int
    message: str
    resultCode: int
    payUrl: str | None = None
    deeplink: str | None = None
    qrCodeUrl: str | None = None
    signature: str | None = None


class MomoIpnPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    partnerCode: str
    orderId: str
    requestId: str
    amount: int
    orderInfo: str
    orderType: str
    transId: int | str
    resultCode: int
    message: str
    payType: str
    responseTime: int
    extraData: str = ""
    signature: str


class MomoQueryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    partnerCode: str
    requestId: str
    orderId: str
    signature: str = ""
    lang: str = "vi"


class MomoQueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    partnerCode: str
    orderId: str
    requestId: str
    extraData: str = ""
    amount: int = 0
    transId: int | str | None = None
    payType: str | None = None
    resultCode: int
    message: str
    responseTime: int = 0
    signature: str | None = None
