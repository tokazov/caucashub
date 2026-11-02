"""Local-only HTTP adapter for the isolated, fake-money billing simulator.

This factory is intentionally not imported or mounted by app.main. In particular,
creating the default disabled app does not even import the sandbox database code.
"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from starlette.middleware.trustedhost import TrustedHostMiddleware


SESSION_COOKIE = "caucashub_billing_sandbox"
SESSION_SECONDS = 60 * 60
STATIC_DIRECTORY = Path(__file__).with_name("static")
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: Literal["alice", "bob"]


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_code: StrictStr = Field(min_length=1, max_length=80)
    target_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["paid", "failed", "cancelled", "expired", "refunded"]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, "message": message})


def _railway_runtime() -> bool:
    return any(
        os.environ.get(name)
        for name in (
            "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID",
            "RAILWAY_ENVIRONMENT_NAME",
        )
    )


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        ):
            return None
        return (
            parsed.scheme, parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except (ValueError, TypeError):
        return None


def create_app(
    enabled: bool = False, db_path=None, project: str = "caucashub", clock=None,
    signing_secret=None,
) -> FastAPI:
    """Build a standalone simulator; never connect to the production database."""
    app = FastAPI(
        title="CaucasHub payment sandbox", docs_url=None, redoc_url=None,
        openapi_url=None,
    )
    billing = None
    demo_customers = {}
    if enabled:
        if _railway_runtime():
            raise ValueError("Payment sandbox is local-only; Railway runtime is refused")
        if db_path is None:
            raise ValueError("An explicit disposable sandbox database path is required")
        # Do not move this import outside the enabled branch: the default app must
        # be inert, without importing database code or reading environment URLs.
        from .core import BillingError, DEMO_CUSTOMERS, SandboxBilling

        billing = SandboxBilling(
            db_path, project=project, clock=clock, signing_secret=signing_secret,
        )
        demo_customers = DEMO_CUSTOMERS

        async def billing_error_handler(_request, exc):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": {
                    "code": exc.code,
                    "message": getattr(exc, "message", str(exc)),
                }},
            )

        app.add_exception_handler(BillingError, billing_error_handler)

    app.state.billing = billing
    app.state.sandbox_enabled = bool(enabled)
    # These are demo-account sessions, not real customer authentication. They are
    # deliberately held only in this local process and contain no real identity.
    sessions: dict[str, tuple[str, float]] = {}
    session_lock = RLock()
    # Cookies are scoped to hosts/paths, not ports. Give every local app its own
    # name so separate projects and parallel instances cannot log each other out.
    cookie_name = f"{SESSION_COOKIE}_{project}_{secrets.token_hex(8)}"
    app.state.sandbox_cookie_name = cookie_name
    app.state.sandbox_sessions = sessions
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]"],
    )

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        if request.url.path.startswith("/api/") and not enabled:
            response = JSONResponse(
                status_code=503,
                content={"detail": {
                    "code": "sandbox_disabled",
                    "message": "Payment sandbox is disabled",
                }},
            )
        elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied_origin = request.headers.get("origin")
            expected = _origin(f"{request.url.scheme}://{request.headers.get('host', '')}")
            fetched_from = request.headers.get("sec-fetch-site")
            if (
                expected is None
                or (supplied_origin is not None and _origin(supplied_origin) != expected)
                or fetched_from not in {None, "same-origin", "none"}
            ):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": {
                        "code": "origin_rejected",
                        "message": "Only same-origin local simulator requests are allowed",
                    }},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def customer(request: Request) -> str:
        token = request.cookies.get(cookie_name, "")
        with session_lock:
            session = sessions.get(token)
            if not session or session[1] <= time.monotonic():
                if session:
                    sessions.pop(token, None)
                raise _error(401, "session_required", "Choose a demo customer first")
            return session[0]

    def customer_view(customer_id: str) -> dict:
        entry = demo_customers[customer_id]
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("title") or customer_id
        else:
            name = str(entry)
        return {"id": customer_id, "name": name}

    @app.get("/health")
    def health():
        return {
            "sandbox": True, "enabled": bool(enabled),
            "status": "ok" if enabled else "disabled", "project": project,
        }

    @app.post("/api/session")
    def choose_customer(body: SessionRequest, request: Request):
        previous = request.cookies.get(cookie_name, "")
        now = time.monotonic()
        with session_lock:
            sessions.pop(previous, None)
            for expired in [key for key, value in sessions.items() if value[1] <= now]:
                sessions.pop(expired, None)
            if len(sessions) >= 2000:
                raise _error(429, "session_limit", "Restart the local simulator to reset demo sessions")
            token = secrets.token_urlsafe(32)
            sessions[token] = (body.customer_id, now + SESSION_SECONDS)
        response = JSONResponse({
            "sandbox": True, "project": project,
            "customer": customer_view(body.customer_id),
        })
        response.set_cookie(
            cookie_name, token, max_age=SESSION_SECONDS, httponly=True,
            samesite="strict", secure=request.url.scheme == "https", path="/api",
        )
        return response

    @app.get("/api/state")
    def state(request: Request):
        customer_id = customer(request)
        return {
            "sandbox": True, "project": project,
            "customer": customer_view(customer_id),
            "catalog": billing.catalog(), "targets": billing.list_targets(customer_id),
            "orders": billing.list_orders(customer_id),
            "grants": billing.list_grants(customer_id), "now": billing.now_iso(),
        }

    @app.post("/api/orders")
    def create_order(
        body: OrderRequest, request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ):
        return billing.create_order(
            customer(request), body.product_code, idempotency_key, target_id=body.target_id,
        )

    @app.get("/api/orders/{order_id}")
    def get_order(order_id: str, request: Request):
        return billing.get_order(customer(request), order_id)

    @app.post("/api/orders/{order_id}/simulate")
    def simulate(order_id: str, body: SimulationRequest, request: Request):
        customer_id = customer(request)
        raw, signature = billing.make_event(customer_id, order_id, body.outcome)
        return billing.accept_event(raw, signature)

    @app.get("/")
    def index():
        document = STATIC_DIRECTORY / "index.html"
        if not document.is_file():
            raise _error(404, "sandbox_ui_missing", "Local sandbox interface is not installed")
        return FileResponse(document)

    app.mount("/assets", StaticFiles(directory=STATIC_DIRECTORY, check_dir=False), name="assets")
    return app
