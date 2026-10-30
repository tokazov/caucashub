"""Local-only browser fixture: real auth/profile routers, disposable SQLite.

Run from a checkout containing the carrier backend and frontend changes:
    python tests/browser/carrier_profile_server.py
No production database, customer accounts, or external notifications are used.
"""
import atexit
from contextlib import asynccontextmanager
from hashlib import sha256
import os
import re
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

REPOSITORY = Path(os.environ.get("CARRIER_PROFILE_REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()
sys.path.insert(0, str(REPOSITORY))
fixture_parent = os.environ.get("CARRIER_BROWSER_TEMP_ROOT")
if fixture_parent:
    fixture_parent = Path(fixture_parent).resolve()
    fixture_parent.mkdir(parents=True, exist_ok=True)
WORKSPACE = TemporaryDirectory(prefix="caucashub-carrier-browser-", dir=fixture_parent)
atexit.register(WORKSPACE.cleanup)
TEMP_ROOT = Path(WORKSPACE.name)
SITE = TEMP_ROOT / "frontend"
DATABASE = TEMP_ROOT / "carrier-browser.sqlite"
PORT = int(os.environ.get("CARRIER_BROWSER_PORT", "8765"))
if not 1024 <= PORT <= 65535:
    raise RuntimeError("Local fixture port must be between1024 and65535")
ORIGIN = f"http://127.0.0.1:{PORT}"
PRODUCTION_API_ORIGIN = "https://api-production-f3ea.up.railway.app"
AUTH_ENABLED = os.environ.get("CARRIER_BROWSER_AUTH") == "1"
NOTIFICATIONS_ENABLED = os.environ.get("CARRIER_BROWSER_NOTIFICATIONS") == "1"
PILOT_ENABLED = os.environ.get("CARRIER_BROWSER_PILOT") == "1"
ADDRESS_ENABLED = os.environ.get("CARRIER_BROWSER_ADDRESS") == "1"
MOCK_MAPS_ENABLED = os.environ.get("CARRIER_BROWSER_MOCK_MAPS") == "1"
if MOCK_MAPS_ENABLED and not ADDRESS_ENABLED:
    raise RuntimeError("Mock maps require the isolated address fixture")
if ADDRESS_ENABLED and not PILOT_ENABLED:
    raise RuntimeError("Address browser tests require the real pilot routes")
if PILOT_ENABLED and os.environ.get("CARRIER_BROWSER_PUBLICATION") != "1":
    raise RuntimeError("Pilot browser tests require the real publication routes")
if AUTH_ENABLED and NOTIFICATIONS_ENABLED:
    raise RuntimeError("Authentication and notification sinks run in separate jobs")
if NOTIFICATIONS_ENABLED and os.environ.get("CARRIER_BROWSER_PUBLICATION") != "1":
    raise RuntimeError("Notification browser tests require actual publication routes")

# Force disposable settings before importing any application modules/settings.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + DATABASE.as_posix()
os.environ["SECRET_KEY"] = "isolated-carrier-browser-fixture-not-production"
os.environ["ALGORITHM"] = "HS256"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TG_BOT_TOKEN"] = ""
os.environ["RESEND_API_KEY"] = ""
os.environ["BREVO_API_KEY"] = ""
os.environ["CAUCASHUB_TG_BOT_TOKEN"] = ""
os.environ["NOTIFICATIONS_WORKER_ENABLED"] = "0"
os.environ["LOCATION_PRESENTATION_ENABLED"] = "0"
os.environ["LOCATIONIQ_KEY"] = ""
if NOTIFICATIONS_ENABLED:
    # These are intentionally unusable provider credentials, intercepted below.
    os.environ["CAUCASHUB_TG_BOT_TOKEN"] = "123456:isolated-browser-test"
    os.environ["BREVO_API_KEY"] = "xkeysib-isolated-browser-test"
    os.environ["RESEND_API_KEY"] = "re_isolated_browser_test"
    os.environ["NOTIFICATIONS_WORKER_ENABLED"] = "0"

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
if MOCK_MAPS_ENABLED:
    # Persistent review runs cannot use Playwright request interception. Supply
    # the same clearly labelled SDK boundary locally and block external hosts.
    index = SITE / "index.html"
    contents = index.read_text(encoding="utf-8")
    contents, changed = re.subn(r"_s\.src = 'https://api-maps\.yandex\.ru/2\.1/\?[^\n]+",
                                "_s.src = 'map-sdk.mock.js';", contents, count=1)
    if changed != 1:
        raise RuntimeError("Expected exactly one Yandex loader in review copy")
    index.write_text(contents.replace("<title>", "<title>ТЕСТ • ", 1), encoding="utf-8")
    sdk = (REPOSITORY / "tests/browser/address_map_sdk.js").read_text(encoding="utf-8")
    for marker, value in {"__REVERSE_FAILS__": "false", "__MAP_SCALE__": "0.005",
                          "__REVERSE_ADDRESS__": "null", "__ROAD_METERS__": "167170.752",
                          "__ROAD_FAILS__": "true", "__REVERSE_PROFILES__": "[]"}.items():
        sdk = sdk.replace(marker, value)
    (SITE / "map-sdk.mock.js").write_text(sdk, encoding="utf-8")
if PILOT_ENABLED:
    print("Pilot fixture: copied isolated frontend", flush=True)
SOURCE_DIGESTS = {name: sha256((SITE / name).read_bytes()).hexdigest()
                  for name in sorted(item.name for item in SITE.iterdir()
                                     if item.is_file() and item.suffix in {".html", ".js", ".css"})}

ORIGINAL_SOURCE_DIGESTS = {name: sha256((frontend / name).read_bytes()).hexdigest()
                           for name in SOURCE_DIGESTS if (frontend / name).is_file()}

APPLICATION_DIGESTS = {}
if ADDRESS_ENABLED:
    application_paths = [
        'app/routers/locations.py', 'app/routers/loads.py', 'app/routers/transport.py',
        'app/models/load.py', 'app/models/transport_offer.py',
        'app/services/route_locations.py', 'app/services/city_identity.py',
        'app/services/location_country.py', 'app/services/location_catalog.json',
        'app/services/location_presentation.py',
    ]
    application_paths += [item.relative_to(REPOSITORY).as_posix()
                          for item in (REPOSITORY / 'app/data').glob('*') if item.is_file()]
    APPLICATION_DIGESTS = {name: sha256((REPOSITORY / name).read_bytes()).hexdigest()
                           for name in application_paths if (REPOSITORY / name).is_file()}

from fastapi import FastAPI, HTTPException, Depends
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
    if PILOT_ENABLED:
        print("Pilot fixture: initializing disposable SQLite", flush=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    if PILOT_ENABLED:
        # Canonical cities belong only to this disposable SQLite fixture.
        # The seed is a local constant catalog and never invokes a geocoder.
        from app.database import AsyncSessionLocal
        from app.services.cities_seed import seed_cities
        async with AsyncSessionLocal() as session:
            await seed_cities(session)
    application.state.ready = True
    if PILOT_ENABLED:
        print("Pilot fixture: ready with real city/stats/trade routers", flush=True)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ORIGIN, f"http://localhost:{PORT}"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def local_fixture_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Carrier-Test-Only"] = "1"
    response.headers["Cache-Control"] = "no-store"
    if MOCK_MAPS_ENABLED:
        response.headers["Content-Security-Policy"] = ("default-src 'self' data: blob:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'")
    return response


# These are the actual application endpoints and dependencies, without mocks.
# They use app.database.engine, which was forced to disposable SQLite above.
app.include_router(auth.router, prefix="/api/auth")
app.include_router(users.router, prefix="/api/users")

# Opt in before the generic boot-data catchall. These are the actual search
# dictionary and dated counter endpoints, backed by the same isolated database.
if PILOT_ENABLED:
    from app.routers import cities, stats
    app.include_router(cities.router, prefix="/api/cities")
    app.include_router(stats.router, prefix="/api/stats")

if ADDRESS_ENABLED:
    from app.routers import locations
    app.include_router(locations.router)

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
    if not NOTIFICATIONS_ENABLED:
        telegram_notify.send_tg_message = successful_no_delivery
        responses.send_email = successful_no_delivery
        # Existing non-notification jobs remain independent of external delivery.
        deals._send_completed_emails = lambda *args, **kwargs: None
    for router, prefix in [
        (loads.router, "/api/loads"), (trucks.router, "/api/trucks"),
        (deals.router, "/api/deals"), (responses.router, ""),
        (transport.router, ""), (transport_requests.router, ""),
        (dictionaries.router, "/api/dictionaries"),
    ]:
        app.include_router(router, prefix=prefix)




if NOTIFICATIONS_ENABLED:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.database import AsyncSessionLocal, get_db
    from app.routers.auth import require_user
    from app.routers import notifications as notification_router
    from app.models.notification import Notification, NotificationDelivery
    from app.services.notifications import utc_iso, clean_data
    from app.services.notification_delivery import dispatch_once
    from notification_sink import NotificationProviderSink

    provider_sink = NotificationProviderSink()
    provider_http = provider_sink.intercept_httpx()
    provider_http.__enter__()
    atexit.register(provider_http.__exit__, None, None, None)
    app.include_router(notification_router.router)

    def synthetic_user(user):
        if not user.email or not user.email.endswith("@example.test"):
            raise HTTPException(404, "Disposable fixture account required")

    async def notification_state_for(user, db):
        synthetic_user(user)
        rows = list((await db.execute(select(Notification).where(
            Notification.recipient_id == user.id).order_by(Notification.id))).scalars())
        identifiers = [row.id for row in rows]
        deliveries = list((await db.execute(select(NotificationDelivery).where(
            NotificationDelivery.notification_id.in_(identifiers)).order_by(
            NotificationDelivery.id))).scalars()) if identifiers else []
        recipients = {user.email, str(user.telegram_id or "")}
        return {
            "test_only": True, "recipient_id": user.id,
            "notifications": [{
                "id": row.id, "recipient_id": row.recipient_id, "actor_id": row.actor_id,
                "event_key": row.event_key, "type": row.kind, "data": clean_data(row.data),
                "created_at": utc_iso(row.created_at), "read_at": utc_iso(row.read_at),
            } for row in rows],
            "deliveries": [{
                "id": row.id, "notification_id": row.notification_id,
                "channel": row.channel, "status": row.status, "attempts": row.attempts,
                "provider_id": row.provider_id,
            } for row in deliveries],
            "provider_attempts": [row for row in provider_sink.attempts if str(row["recipient"]) in recipients],
            "unexpected_provider_requests": len(provider_sink.unexpected),
        }

    @app.post("/__test__/notification-link")
    async def link_test_channel(current_user: User = Depends(require_user),
                                db: AsyncSession = Depends(get_db)):
        synthetic_user(current_user)
        chat = str(901000000 + current_user.id)
        current_user.telegram_id = chat
        await db.commit()
        provider_sink.allow(telegram_ids=[chat], emails=[current_user.email])
        return {"test_only": True, "user_id": current_user.id,
                "telegram_id": chat, "email": current_user.email}

    @app.get("/__test__/notification-state")
    async def test_notification_state(current_user: User = Depends(require_user),
                                      db: AsyncSession = Depends(get_db)):
        return await notification_state_for(current_user, db)

    @app.post("/__test__/notification-drain")
    async def drain_test_notifications(current_user: User = Depends(require_user)):
        synthetic_user(current_user)
        before = len(provider_sink.attempts)
        stats = await dispatch_once(sessions=AsyncSessionLocal, limit=100)
        return {"test_only": True, "stats": stats,
                "new_provider_attempts": len(provider_sink.attempts) - before,
                "unexpected_provider_requests": len(provider_sink.unexpected)}



# Local-only password recovery mailbox. It records the real email body produced
# by the real auth route and rejects any recipient outside disposable accounts.
if AUTH_ENABLED:
    from app.services import notification_channels

    auth_emails = []

    async def capture_auth_email(to, subject, html, *, idempotency_key=None):
        if not isinstance(to, str) or not to.endswith("@example.test"):
            raise RuntimeError("Only synthetic fixture recipients are allowed")
        auth_emails.append({"to": to, "subject": subject, "html": html})
        return notification_channels.DeliveryResult("sent", provider_id="isolated-auth-mail")

    notification_channels.send_email = capture_auth_email

    @app.get("/__test__/emails")
    async def test_auth_emails(recipient: str):
        if not recipient.endswith("@example.test"):
            raise HTTPException(404, "Disposable fixture recipient required")
        return {"test_only": True, "emails": [
            row for row in auth_emails if row["to"] == recipient
        ]}


@app.get("/__test__/ready")
async def ready():
    return {
        "test_only": True,
        "isolated_sqlite": (engine.url.drivername == "sqlite+aiosqlite"
                            and Path(engine.url.database).resolve() == DATABASE.resolve()),
        "actual_profile_routers": True,
        "notification_test": NOTIFICATIONS_ENABLED,
        "auth_test": AUTH_ENABLED,
        "pilot_test": PILOT_ENABLED,
        "actual_city_stats_routers": PILOT_ENABLED,
        "address_test": ADDRESS_ENABLED,
        "actual_location_routers": ADDRESS_ENABLED,
        "mock_maps": MOCK_MAPS_ENABLED,
        "source_sha256": SOURCE_DIGESTS,
        "original_source_sha256": ORIGINAL_SOURCE_DIGESTS,
        "backend_sha256": APPLICATION_DIGESTS,
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
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
