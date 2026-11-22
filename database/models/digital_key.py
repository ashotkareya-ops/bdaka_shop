from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import Base

class DigitalKey(Base):
    __tablename__ = "digital_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    product = relationship("Product", back_populates="keys")
    order = relationship("Order", back_populates="digital_key")
