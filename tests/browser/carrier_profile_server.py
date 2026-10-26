"""Local-only browser fixture: real auth/profile routers, disposable SQLite.

Run from a checkout containing the carrier backend and frontend changes:
    python tests/browser/carrier_profile_server.py
No production database, customer accounts, or external notifications are used.
"""
import atexit
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

REPOSITORY = Path(os.environ.get("CARRIER_PROFILE_REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()
sys.path.insert(0, str(REPOSITORY))
WORKSPACE = TemporaryDirectory(prefix="caucashub-carrier-browser-")
atexit.register(WORKSPACE.cleanup)
TEMP_ROOT = Path(WORKSPACE.name)
SITE = TEMP_ROOT / "frontend"
DATABASE = TEMP_ROOT / "carrier-browser.sqlite"
ORIGIN = "http://127.0.0.1:8765"
PRODUCTION_API_ORIGIN = "https://api-production-f3ea.up.railway.app"

# Force disposable settings before importing any application modules/settings.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + DATABASE.as_posix()
os.environ["SECRET_KEY"] = "isolated-carrier-browser-fixture-not-production"
os.environ["ALGORITHM"] = "HS256"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TG_BOT_TOKEN"] = ""
os.environ["RESEND_API_KEY"] = ""

frontend = REPOSITORY / "frontend"
if not (frontend / "index.html").is_file():
    raise RuntimeError("Run this test fixture in the actual repository checkout")
shutil.copytree(frontend, SITE)
for asset in SITE.rglob("*"):
    if asset.is_file() and asset.suffix in {".js", ".html"}:
        contents = asset.read_text(encoding="utf-8")
        if PRODUCTION_API_ORIGIN in contents:
            # This covers API_BASE AND hardcoded settings/hydration origins.
            asset.write_text(contents.replace(PRODUCTION_API_ORIGIN, ORIGIN), encoding="utf-8")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.database import Base, engine
from app.models.user import User
from app.routers import auth, users
from app.services import telegram_notify


async def no_owner_notification(**kwargs):
    """Registration uses its real route but never sends an external message."""
    return None


telegram_notify.notify_owner_new_user = no_owner_notification
auth._login_attempts.clear()
if not hasattr(User, "truck_type") or not hasattr(User, "tonnage"):
    raise RuntimeError("The real carrier profile backend must be present for this browser test")


@asynccontextmanager
async def lifespan(application):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    application.state.ready = True
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ORIGIN, "http://localhost:8765"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def local_fixture_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Carrier-Test-Only"] = "1"
    response.headers["Cache-Control"] = "no-store"
    return response


# These are the actual application endpoints and dependencies, without mocks.
# They use app.database.engine, which was forced to disposable SQLite above.
app.include_router(auth.router, prefix="/api/auth")
app.include_router(users.router, prefix="/api/users")

# A separate later publication-browser job may opt into the real trade routes.
# Profile regression remains independent of that wider journey.
if os.environ.get("CARRIER_BROWSER_PUBLICATION") == "1":
    from app.routers import loads, trucks, deals, responses, transport, transport_requests, dictionaries
    from app.services import exchange_rate, subscription_matcher, transport_matcher

    async def no_delivery(*args, **kwargs):
        return 0

    async def successful_no_delivery(*args, **kwargs):
        return True

    async def fixed_test_exchange_rate(*args, **kwargs):
        return 2.7

    exchange_rate.get_usd_gel_rate = fixed_test_exchange_rate
    subscription_matcher.notify_subscribers = no_delivery
    transport_matcher.notify_transport_subscribers = no_delivery
    telegram_notify.send_tg_message = successful_no_delivery
    responses.send_email = successful_no_delivery
    # Completion tests exercise real state changes without external email delivery.
    from app import email_utils
    email_utils.send_deal_status_email = successful_no_delivery
    for router, prefix in [
        (loads.router, "/api/loads"), (trucks.router, "/api/trucks"),
        (deals.router, "/api/deals"), (responses.router, ""),
        (transport.router, ""), (transport_requests.router, ""),
        (dictionaries.router, "/api/dictionaries"),
    ]:
        app.include_router(router, prefix=prefix)



@app.get("/__test__/ready")
async def ready():
    return {
        "test_only": True,
        "isolated_sqlite": True,
        "actual_profile_routers": True,
        "ready": app.state.ready,
        "origin": ORIGIN,
    }


@app.get("/api/{path:path}")
async def optional_boot_data(path: str):
    """Only unrelated read-only boot widgets are stubbed; never auth/profile."""
    path = path.strip("/")
    if path.startswith(("users/", "auth/")):
        raise HTTPException(404, "No auth/profile fixtures: real routers are required")
    if path in {"loads", "loads/my/loads"}:
        return {"loads": [], "total": 0}
    if path == "trucks":
        return {"trucks": [], "total": 0}
    if path == "transport":
        return {"offers": [], "total": 0}
    if path == "stats/counters":
        return {"active_loads": 0, "online_trucks": 0, "companies": 0,
                "total_users": 0, "online_users": 0}
    if path == "deals/my":
        return {"deals": []}
    if path == "responses/my":
        return {"responses": []}
    if path in {"subscriptions", "transport-subscriptions"}:
        return {"subscriptions": []}
    if path == "payments/my":
        return {"payments": []}
    if path == "tg/status":
        return {"linked": False}
    if path.startswith("ads/"):
        return {"ad": None}
    raise HTTPException(404, "Unconfigured local boot endpoint")


app.mount("/", StaticFiles(directory=SITE, html=True), name="test_frontend")


if __name__ == "__main__":
    # Do not expose this test fixture beyond the local runner.
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
