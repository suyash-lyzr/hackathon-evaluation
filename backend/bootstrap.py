"""Runtime bootstrap for containerized deployments.

If MONGO_TLS_CA_B64 is set (base64-encoded cert contents), decode it to a file
on disk and rewrite the `tlsCAFile=...` path in DB_URL to point at it. This
lets us ship the cert via a Railway/Fly env var instead of baking it into the
image.

Safe no-op if MONGO_TLS_CA_B64 is unset (local dev path).
"""
import base64
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def bootstrap_runtime() -> None:
    ca_b64 = os.environ.get("MONGO_TLS_CA_B64")
    if not ca_b64:
        return

    target = Path(os.environ.get("MONGO_TLS_CA_PATH", "/data/cred.pem"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(ca_b64))
        target.chmod(0o600)
    except Exception as e:
        logger.error(f"bootstrap: failed to write cert to {target}: {e}")
        raise

    logger.info(f"bootstrap: wrote Mongo TLS CA to {target}")

    db_url = os.environ.get("DB_URL", "")
    if db_url and "tlsCAFile=" in db_url:
        os.environ["DB_URL"] = re.sub(r"tlsCAFile=[^&]+", f"tlsCAFile={target}", db_url)
        logger.info("bootstrap: rewrote tlsCAFile in DB_URL")
