from dataclasses import dataclass
from typing import Any


@dataclass
class AuthContext:
    token: str
    record: dict[str, Any]
