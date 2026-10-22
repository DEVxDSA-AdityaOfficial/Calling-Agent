"""Maintenance commands.

    python -m app.cli migrate        # alembic upgrade head
    python -m app.cli rotate-keys    # re-encrypt every stored credential with the first ENCRYPTION_KEY

Key rotation: put the NEW key first in ENCRYPTION_KEY (comma-separated, old keys after it), run
`rotate-keys`, then remove the old keys.
"""

import sys

from .db import SessionLocal, run_migrations
from .models import ProviderCredential, utcnow
from .security import rotate_token


def rotate_keys() -> int:
    count = 0
    with SessionLocal() as db:
        for cred in db.query(ProviderCredential).all():
            if cred.secrets_encrypted:
                cred.secrets_encrypted = rotate_token(cred.secrets_encrypted)
                cred.secrets_rotated_at = utcnow()
                count += 1
        db.commit()
    return count


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "migrate":
        run_migrations()
        print("Database is at the latest migration.")
    elif cmd == "rotate-keys":
        print(f"Re-encrypted {rotate_keys()} credential(s) with the primary key.")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
