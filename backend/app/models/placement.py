from sqlalchemy import Column, Integer, Boolean, Text, Date, DateTime, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db.base import Base


class Placement(Base):
    __tablename__ = "placements"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = Column(UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.id"), nullable=False)

    # Placement Details
    placed_at = Column(DateTime, default=datetime.utcnow)
    start_date = Column(Date, nullable=True)
    salary = Column(Integer, nullable=True)
    equity = Column(Numeric(5, 2), nullable=True)

    # Fee
    fee_amount = Column(Integer, nullable=True)
    fee_paid_at = Column(DateTime, nullable=True)

    # Retention
    still_employed_6m = Column(Boolean, nullable=True)
    still_employed_12m = Column(Boolean, nullable=True)

    # Notes
    notes = Column(Text, nullable=True)
