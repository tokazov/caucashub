"""Shared calendar-day rules for public listings (Georgia local time).

Queries hide expired listings without deleting history or altering deal statuses.
Naive database timestamps are treated as UTC, matching existing API storage.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func

GEORGIA = ZoneInfo("Asia/Tbilisi")


def listing_day_start(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(GEORGIA).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)


def current_load_conditions(now=None):
    from app.models.load import Load, LoadStatus
    return (Load.status == LoadStatus.active,
            Load.load_date >= listing_day_start(now),
            Load.is_demo.is_(False))


def current_transport_conditions(now=None):
    from app.models.transport_offer import TransportOffer
    return (TransportOffer.status == "active",
            func.coalesce(TransportOffer.available_to,
                          TransportOffer.available_from) >= listing_day_start(now),
            TransportOffer.is_demo.is_(False))


def date_is_current(value, now=None):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value >= listing_day_start(now)
