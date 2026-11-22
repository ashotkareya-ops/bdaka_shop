from datetime import datetime
from sqlalchemy import Float, ForeignKey, String, DateTime, Integer, Integer, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import Base

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    price: Mapped[float] = mapped_column(Float)  # total order amount
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    supplier_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    digital_key = relationship("DigitalKey", back_populates="order")
