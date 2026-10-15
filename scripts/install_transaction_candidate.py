"""Install only transaction files after a verified rollback bundle exists."""

import hashlib
import json
import shutil
import sys
from pathlib import Path


def main():
    candidate = Path(__file__).resolve().parents[1]
    live = Path.home() / "Nexa-Client-BE"
    backup = Path(sys.argv[1])
    if (
        not (backup / "source.tar.gz").is_file()
        or not (backup / "schema-applied.json").is_file()
    ):
        raise RuntimeError("Verified backup and applied schema required")
    paths = [
        "app/application/access.py",
        "app/infrastructure/operation_lock.py",
        "app/application/services/order_policy.py",
        "app/application/services/booking_policy.py",
        "app/application/services/transactional_service.py",
        "app/application/services/transaction_gateway.py",
        "app/application/services/legacy_booking_service.py",
        "app/application/services/public_submission_service.py",
        "app/interface/transaction_dependencies.py",
        "app/interface/routes/transactional.py",
        "app/interface/dto/transactional.py",
        "scripts/reconcile_bookings.py",
    ]
    manifest = {}
    for name in paths:
        source, destination = candidate / name, live / name
        manifest[name] = {
            "before": hashlib.sha256(destination.read_bytes()).hexdigest()
            if destination.exists()
            else None,
            "after": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    (backup / "transaction-install-manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )
    for name in paths:
        source, destination = candidate / name, live / name
        shutil.copy2(source, destination)
        if (
            hashlib.sha256(destination.read_bytes()).hexdigest()
            != manifest[name]["after"]
        ):
            raise RuntimeError("Installed hash mismatch")
    print("Installed and hash-verified", len(paths), "transaction files")


if __name__ == "__main__":
    main()
