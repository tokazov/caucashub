"""Post-deployment public GET smoke check; never a pre-backend CI dependency."""
import json
from scripts.wait_for_api_release import get


def count(value):
    return type(value) is int and value >= 0


def summary(counters, directory, available, trucks):
    if not all(isinstance(value, dict) for value in (counters, directory, available, trucks)):
        raise ValueError("Public API must return objects")
    counts = (counters.get("total_users"), counters.get("companies"),
              directory.get("total"), available.get("total"), trucks.get("total"))
    if not all(count(value) for value in counts) or counts[2] < counts[3]:
        raise ValueError("Public counts are invalid or inconsistent")
    rows, current = directory.get("offers"), available.get("offers")
    if (not isinstance(rows, list) or not isinstance(current, list)
            or len(rows) > counts[2] or len(current) > counts[3]):
        raise ValueError("Public listing data is incomplete")
    if any(not isinstance(row, dict) or type(row.get("dates_expired")) is not bool
           for row in rows + current):
        raise ValueError("Public listing freshness schema is missing")
    if any(row["dates_expired"] for row in current):
        raise ValueError("Available-only listing contains an expired offer")
    # An empty marketplace is legitimate; never require manufactured activity.
    return dict(zip(("total_users", "companies", "transport_total", "current_transport_total", "truck_total"), counts),
                expired_dates_visible=sum(row["dates_expired"] for row in rows), release_schema_seen=True)


def main():
    result = summary(get("/api/stats/counters"), get("/api/transport/?limit=200"),
                     get("/api/transport/?limit=200&available_only=true"), get("/api/trucks/?limit=200"))
    # Aggregates only: no customer names, contact details, or credentials.
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
