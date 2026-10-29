"""Shared calendar-day rules for public listings (Georgia local time).

Queries hide expired listings without deleting history or altering deal statuses.
Naive database timestamps are treated as UTC, matching existing API storage.
"""
from datetime import date, datetime, time, timezone, timedelta
import re
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
            func.coalesce(Load.load_date_end, Load.load_date) >= listing_day_start(now),
            Load.is_demo.is_(False))


def current_transport_conditions(now=None):
    from app.models.transport_offer import TransportOffer
    return (TransportOffer.status == "active",
            func.coalesce(TransportOffer.available_to,
                          TransportOffer.available_from) >= listing_day_start(now),
            TransportOffer.is_demo.is_(False))


def date_is_current(value, now=None):
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value >= listing_day_start(now)


def transport_availability_metadata(offer, now=None):
    """Seven days is a pilot mark-only rule; no query hides listings by it.

    Null legacy confirmation stays unknown. Views or ordinary metadata edits do
    not renew availability. Date expiry remains the established calendar rule.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    confirmed = getattr(offer, "last_confirmed_at", None)
    if confirmed is not None and confirmed.tzinfo is None:
        confirmed = confirmed.replace(tzinfo=timezone.utc)
    expired = not date_is_current(offer.available_to or offer.available_from, now)
    status = ("expired" if expired else "unconfirmed" if confirmed is None else
              "stale" if confirmed < now - timedelta(days=7) else "confirmed")
    return {"last_confirmed_at": confirmed.isoformat() if confirmed else None,
            "availability_status": status, "confirmation_ttl_days": 7}



def loading_day(value):
    """Read legacy naive timestamps as UTC; return the Georgian calendar day."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(GEORGIA).date()


def parse_loading_day(value):
    """Accept calendar dates, dd.mm.yy and ISO timestamps; store midnight in UTC."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if re.fullmatch(r"\d{2}\.\d{2}\.(\d{2}|\d{4})", value):
            day, month, year = map(int, value.split('.'))
            value = date(year + 2000 if year < 100 else year, month, day)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            value = date.fromisoformat(value)
        else:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if isinstance(value, datetime):
        value = loading_day(value)
    if not isinstance(value, date):
        raise ValueError("Укажите корректную дату загрузки")
    return datetime.combine(value, time.min, GEORGIA).astimezone(timezone.utc)
