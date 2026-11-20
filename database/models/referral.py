from datetime import datetime
from sqlalchemy import ForeignKey, Float, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base

class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    invited_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    reward_amount: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
