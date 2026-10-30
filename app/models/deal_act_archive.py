"""Insert-only copies of both language variants of a privately issued act."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, LargeBinary, String
from sqlalchemy.sql import func

from app.database import Base


class DealActArchive(Base):
    __tablename__ = 'deal_act_archives'
    __table_args__ = (
        CheckConstraint('schema_version = 1', name='ck_deal_act_archive_version'),
        CheckConstraint('length(ru_pdf) > 0', name='ck_deal_act_archive_ru_pdf'),
        CheckConstraint('length(ge_pdf) > 0', name='ck_deal_act_archive_ge_pdf'),
        CheckConstraint('length(ru_sha256) = 64', name='ck_deal_act_archive_ru_sha'),
        CheckConstraint('length(ge_sha256) = 64', name='ck_deal_act_archive_ge_sha'),
        CheckConstraint('length(payload_sha256) = 64', name='ck_deal_act_archive_payload_sha'),
    )

    deal_id = Column(Integer, ForeignKey('deals.id'), primary_key=True, autoincrement=False)
    schema_version = Column(Integer, nullable=False, server_default='1')
    issued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    payload = Column(JSON, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    ru_pdf = Column(LargeBinary, nullable=False)
    ge_pdf = Column(LargeBinary, nullable=False)
    ru_sha256 = Column(String(64), nullable=False)
    ge_sha256 = Column(String(64), nullable=False)
