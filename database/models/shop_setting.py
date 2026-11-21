from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base


class ShopSetting(Base):
    __tablename__ = "shop_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
