import asyncio
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger("subprocess")

SITES_COLLECTION = "sites"


def sanitize_name(name: str, max_length: Optional[int] = None) -> str:
    """Lowercase, replace non-alphanumeric with hyphens, strip, optionally truncate."""
    name = re.sub(r"[^a-z0-9-]", "-", name.lower())
    name = re.sub(r"-+", "-", name).strip("-")
    if max_length and len(name) > max_length:
        name = name[:max_length]
    return name or "default"


async def run_subprocess(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 300,
    shell: bool = False,
    env: Optional[dict] = None,
) -> tuple[int, str, str]:
    """Run a subprocess asynchronously and return (returncode, stdout, stderr)."""
    merged_env = {**os.environ, **(env or {})} if env else None

    def _run():
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=shell,
            env=merged_env,
        )

    try:
        result = await asyncio.to_thread(_run)
        if result.returncode != 0 and result.stderr:
            logger.error(
                "subprocess stderr",
                extra={"cmd": cmd[0] if cmd else "", "stderr": result.stderr[:1000]},
            )
        elif result.stderr:
            logger.warning(
                "subprocess stderr (non-fatal)",
                extra={"cmd": cmd[0] if cmd else "", "stderr": result.stderr[:500]},
            )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s"


def utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()
