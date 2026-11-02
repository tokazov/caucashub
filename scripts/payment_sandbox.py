"""Run the fake-money sandbox on loopback, without importing production settings."""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Isolated CaucasHub payment simulator. No bank calls or real charges.",
    )
    parser.add_argument(
        "--enable-sandbox", action="store_true",
        help="Explicitly enable the local fake-money simulator",
    )
    parser.add_argument("--port", type=int, default=8878)
    parser.add_argument("--project", choices=("caucashub", "techrent"), default="caucashub")
    args = parser.parse_args(argv)
    if not args.enable_sandbox:
        parser.error("Pass --enable-sandbox to run; the default is disabled")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if any(os.environ.get(name) for name in (
        "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID",
        "RAILWAY_ENVIRONMENT_NAME",
    )):
        parser.error("The simulator must run locally, outside a Railway runtime")

    # This script never reads DATABASE_URL, .env, application settings, or bank
    # credentials. Every run creates its own new SQLite file in the checkout.
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts" / "payment-sandbox"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    descriptor, database_path = tempfile.mkstemp(
        prefix="session-", suffix=".sandbox.sqlite3", dir=artifact_dir,
    )
    os.close(descriptor)

    from app.billing_sandbox.api import create_app
    import uvicorn

    app = create_app(enabled=True, db_path=database_path, project=args.project)
    print(f"FAKE MONEY ONLY: http://127.0.0.1:{args.port}", flush=True)
    print(f"Disposable sandbox database: {database_path}", flush=True)
    uvicorn.run(
        app, host="127.0.0.1", port=args.port, reload=False,
        proxy_headers=False, server_header=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
