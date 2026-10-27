"""Administrative credentials are explicitly configured; missing means disabled."""
import hmac
import os


def admin_secret_matches(candidate: str | None) -> bool:
    configured = os.environ.get("ADMIN_SECRET", "")
    return bool(
        configured and isinstance(candidate, str) and candidate
        and hmac.compare_digest(candidate.encode("utf-8"), configured.encode("utf-8"))
    )
