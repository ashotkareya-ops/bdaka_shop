from sqlalchemy import String, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    integration_type: Mapped[str] = mapped_column(String(40), default="manual")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
