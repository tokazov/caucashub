"""One attributable review per participant and deal; no legacy backfill."""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.sql import func
from app.database import Base


class DealReview(Base):
    __tablename__ = "deal_reviews"
    __table_args__ = (
        UniqueConstraint("deal_id", "rater_id", name="uq_deal_reviews_deal_rater"),
        CheckConstraint("score >= 1 AND score <= 5", name="ck_deal_reviews_score_range"),
        CheckConstraint("rater_id <> recipient_id", name="ck_deal_reviews_distinct_people"),
    )

    id = Column(Integer, primary_key=True)
    deal_id = Column(Integer, ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True)
    rater_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
