from datetime import datetime
from sqlalchemy import String, Float, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base

class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    discount_percent: Mapped[float] = mapped_column(Float, default=0)
    uses_left: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
