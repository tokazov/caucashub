"""Publish frontend only after the matching Railway API is healthy and typed-ready.

Only public read-only GETs. No provider credentials or customer data are logged.
"""
import argparse
import json
import re
import time
from urllib.request import Request, urlopen

API = "https://api-production-f3ea.up.railway.app"

def matching_release(health, places, commit):
    return (isinstance(health, dict) and health.get("status") == "healthy"
            and health.get("release") == commit and isinstance(places, dict)
            and any(isinstance(row, dict) and row.get("kind") == "border_checkpoint"
                    and row.get("key") == "ge:dariali-checkpoint"
                    and row.get("country_iso") == "GE"
                    for row in places.get("results", [])))

def listings_ready(loads, transport):
    if not isinstance(loads, dict) or not isinstance(transport, dict):
        return False
    cargo, offers = loads.get("loads"), transport.get("offers")
    if not isinstance(cargo, list) or not isinstance(offers, list):
        return False
    return (all(isinstance(row, dict) and {"from_location", "to_location"} <= row.keys() for row in cargo)
            and all(isinstance(row, dict) and {"from_location", "to_location", "last_confirmed_at"} <= row.keys() for row in offers))

def get(path):
    request = Request(API + path, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)

def wait(commit, timeout=600):
    deadline = time.monotonic() + timeout
    while True:
        try:
            health = get("/health")
            places = get("/api/locations/suggest?q=Dariali&limit=10")
            if matching_release(health, places, commit) and listings_ready(
                    get("/api/loads/?limit=1"), get("/api/transport/?limit=1")):
                print("Matching healthy API is ready; frontend may publish.")
                return
            print("Waiting for matching healthy API release...")
        except Exception as error:
            print("API release is not ready (" + type(error).__name__ + ").")
        if time.monotonic() >= deadline:
            raise TimeoutError("Matching API did not become ready; frontend publication stopped")
        time.sleep(min(10, max(0, deadline-time.monotonic())))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if not re.fullmatch("[a-fA-F0-9]{40}", args.commit) or not 1 <= args.timeout <= 1200:
        parser.error("A full commit SHA and a bounded timeout are required")
    wait(args.commit, args.timeout)

if __name__ == "__main__":
    main()
