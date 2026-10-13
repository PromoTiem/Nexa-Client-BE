"""Host-wide advisory locks for workflows that update multiple PB records.

All backend processes must share this directory. These locks do not coordinate
multiple hosts; that topology requires a database-side compare-and-swap.
"""

import asyncio
import fcntl
import hashlib
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path


@asynccontextmanager
async def operation_lock(name: str):
    directory = Path(tempfile.gettempdir()) / f"nexa-operation-locks-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Unsafe operation lock directory")
    path = directory / hashlib.sha256(name.encode()).hexdigest()
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        yield
    finally:
        os.close(fd)
