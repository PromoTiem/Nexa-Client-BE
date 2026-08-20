from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class AuthContext:
    token: str
    record: Dict[str, Any]
