from typing import Literal

from pydantic import BaseModel

from app.application.serve_models import (
    PipelineBuild as PipelineBuild,
)
from app.application.serve_models import (
    PipelineDomain as PipelineDomain,
)
from app.application.serve_models import (
    PipelineResponse as PipelineResponse,
)
from app.application.serve_models import (
    PipelineServe as PipelineServe,
)
from app.application.serve_models import (
    ServeStateResponse as ServeStateResponse,
)
from app.application.serve_models import (
    SiteServeResponse as SiteServeResponse,
)
from app.application.serve_models import (
    SiteStopResponse as SiteStopResponse,
)

ManualServeStatus = Literal["requested", "verifying", "verified", "failed"]


class ServeStatusPatchRequest(BaseModel):
    status: ManualServeStatus
