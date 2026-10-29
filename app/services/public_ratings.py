"""Public ratings come from attributable reviews of confirmed completed deals.

Legacy User.rating/counters remain history and are never a public rating source.
"""
from sqlalchemy import and_, or_, select, func

from app.models.deal import Deal, DealStatus
from app.models.deal_review import DealReview


def public_rating_fields(summary=None):
    summary = summary or {}
    count = int(summary.get("review_count", 0))
    return {"rating": summary.get("rating") if count else None,
            "review_count": count, "rating_verified": bool(count),
            "is_new_carrier": not bool(count)}


async def public_ratings(db, user_ids):
    ids = {int(value) for value in user_ids if value is not None}
    if not ids:
        return {}
    result = await db.execute(
        select(DealReview.recipient_id, func.avg(DealReview.score), func.count(DealReview.id))
        .join(Deal, Deal.id == DealReview.deal_id)
        .where(DealReview.recipient_id.in_(ids),
               Deal.status.in_([DealStatus.completed, DealStatus.rated]),
               Deal.shipper_confirmed.is_(True), Deal.carrier_confirmed.is_(True),
               or_(and_(DealReview.rater_id == Deal.shipper_id,
                        DealReview.recipient_id == Deal.carrier_id),
                   and_(DealReview.rater_id == Deal.carrier_id,
                        DealReview.recipient_id == Deal.shipper_id)))
        .group_by(DealReview.recipient_id)
    )
    return {recipient: {"rating": round(float(mean), 1), "review_count": count}
            for recipient, mean, count in result.all()}
