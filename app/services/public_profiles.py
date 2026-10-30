"""Allowlisted public accounts and consent-aware, attributable review summaries."""
from datetime import timezone
import re

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models.deal import Deal
from app.models.deal_review import DealReview
from app.models.user import User
from app.services.normalizers import sanitize_text
from app.services.public_ratings import (
    confirmed_completed_deal, eligible_public_review, public_rating_fields, public_ratings,
)


def _available(user):
    return bool(user is not None and not user.is_deleted and user.is_active)


def _role(user):
    value = getattr(user.role, 'value', user.role) if user else None
    return value if value in ('carrier', 'shipper', 'both') else None


def _text(value, limit=200):
    if not isinstance(value, str) or not value.strip():
        return None
    value = sanitize_text(value.strip(), max_length=limit + 512)
    value = re.sub(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', '•••', value)
    value = re.sub(r'\+?\d(?:[\s().\-]*\d){6,}', '•••', value)
    return value[:limit]


def _public_name(value):
    value = _text(value)
    if value and re.search(r'[^\W\d_]', value.replace('•••', ''), re.UNICODE):
        return value
    return None


def _name(user):
    # The shared display_name fallback contains the email local-part; public
    # profiles must never derive a name from any contact detail.
    return _public_name(user.company_name) or _public_name(user.full_name) or 'Участник CaucasHub'


def _author(user):
    if not _available(user):
        return {'id': None, 'name': 'Участник CaucasHub', 'role': None, 'available': False}
    return {'id': user.id, 'name': _name(user), 'role': _role(user), 'available': True}


async def public_profile(db, user_id, *, limit=10, offset=0):
    user = await db.get(User, user_id)
    if not _available(user):
        raise HTTPException(404, 'Профиль недоступен')
    rating = public_rating_fields((await public_ratings(db, [user_id])).get(user_id))
    completed = (await db.execute(select(func.count(Deal.id)).where(
        confirmed_completed_deal(), or_(Deal.shipper_id == user_id, Deal.carrier_id == user_id)))).scalar_one()
    from app.services.city_identity import _canonical_registry
    raw_city = user.city if isinstance(user.city, str) else ''
    city = _canonical_registry.resolve(raw_city) if not any(mark in raw_city for mark in (',', ';', '\n', '\r')) else None
    profile = {'id': user.id, 'name': _name(user), 'company_name': _public_name(user.company_name),
               'role': _role(user), 'city': city.name_ru if city else None, 'is_verified': bool(user.is_verified),
               **rating, 'completed_deals_count': completed}
    rows = (await db.execute(select(DealReview).join(Deal, Deal.id == DealReview.deal_id).where(
        DealReview.recipient_id == user_id, eligible_public_review())
        .order_by(DealReview.created_at.desc(), DealReview.id.desc()).limit(limit).offset(offset))).scalars().all()
    author_ids = {row.rater_id for row in rows}
    authors = {author.id: author for author in (await db.execute(
        select(User).where(User.id.in_(author_ids)))).scalars().all()} if author_ids else {}
    reviews = []
    for row in rows:
        author = _author(authors.get(row.rater_id))
        visible = bool(row.public_comment and author['available'])
        created = row.created_at
        if created is not None:
            created = (created if created.tzinfo else created.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        reviews.append({'id': row.id, 'score': row.score,
                        'comment': _text(row.comment, 2000) if visible else None,
                        'public_comment': visible, 'created_at': created.isoformat() if created else None,
                        'author': author})
    total = rating['review_count']
    return {'profile': profile, 'reviews': reviews, 'total': total,
            'limit': limit, 'offset': offset, 'has_more': offset + len(reviews) < total}
