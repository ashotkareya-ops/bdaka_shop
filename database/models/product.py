from datetime import datetime
from sqlalchemy import String, Float, Boolean, ForeignKey, Text, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(180))
    price: Mapped[float] = mapped_column(Float, default=0.0)  # retail price
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    supplier_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    supplier_product_id: Mapped[int | None] = mapped_column(nullable=True)
    supplier_cost: Mapped[float | None] = mapped_column(Float, nullable=True)  # supplier retail catalog price (not wholesale)
    markup_percent: Mapped[float] = mapped_column(Float, default=30.0, nullable=False)
    supplier_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supplier_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    category = relationship("Category", back_populates="products")
    keys = relationship("DigitalKey", back_populates="product")
