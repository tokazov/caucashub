"""Read-only smoke of integrated real pilot routers in disposable SQLite.

No listening socket, account, listing, or external notification is created.
"""
import asyncio
import json
import os
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "pilot-fixture-smoke"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
os.environ.update({
    "CARRIER_PROFILE_REPO_ROOT": str(ROOT),
    "CARRIER_BROWSER_TEMP_ROOT": str(ARTIFACTS / ".fixture"),
    "CARRIER_BROWSER_PUBLICATION": "1", "CARRIER_BROWSER_NOTIFICATIONS": "1",
    "CARRIER_BROWSER_AUTH": "0", "CARRIER_BROWSER_PILOT": "1",
})
fixture = runpy.run_path(str(ROOT / "tests/browser/carrier_profile_server.py"), run_name="pilot_fixture_smoke")


async def main():
    import httpx
    app = fixture["app"]
    report = {"test_only": True, "listening_socket": False, "accounts_created": 0,
              "listings_created": 0, "aliases": []}
    async with app.router.lifespan_context(app):
        assert fixture["DATABASE"].is_file()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://127.0.0.1:8765") as client:
            async def get(path, **kwargs):
                response = await client.get(path, **kwargs)
                assert response.status_code == 200, (path, response.status_code, response.text)
                assert response.headers["X-Carrier-Test-Only"] == "1"
                return response.json()

            ready = await get("/__test__/ready")
            assert ready["isolated_sqlite"] and ready["actual_city_stats_routers"]
            report["source_sha256"] = ready["source_sha256"]
            identities = set()
            for query in ("Тбилиси", "Tbilisi", "თბილისი"):
                dictionary = await get("/api/cities/", params={"q": query})
                city = next(row for row in dictionary["cities"] if row["canonical_key"] == "ge:tbilisi")
                identities.add((city["id"], city["canonical_key"]))
                suggestions = await get("/api/cities/search", params={"q": query, "lang": "ge"})
                assert any(row["canonical_key"] == "ge:tbilisi" for row in suggestions["results"])
                report["aliases"].append({"query": query, "id": city["id"], "key": city["canonical_key"]})
            assert len(identities) == 1
            for scope in ("local", "intl"):
                transport = await get("/api/transport/", params={"scope": scope, "from_city": "თბილისი"})
                loads = await get("/api/loads/", params={"scope": scope, "from_city": "Tbilisi"})
                assert transport["offers"] == [] and loads["loads"] == []
            counters = await get("/api/stats/counters")
            assert counters["registered_profiles"] == 0
            assert counters["companies_metric"] == "named_user_profiles_not_verified_legal_entities"
            assert counters["as_of"]
            report["counters"] = counters
    sink = fixture["provider_sink"]
    assert not sink.attempts and not sink.unexpected
    report.update({"provider_attempts": 0, "unexpected_provider_requests": 0, "status": "passed"})
    (ARTIFACTS / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Pilot fixture smoke passed: real city/stats/list routers, 3 aliases, isolated SQLite, no external requests")


if __name__ == "__main__":
    asyncio.run(main())
