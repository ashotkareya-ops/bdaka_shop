from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from database.models.shop_setting import ShopSetting

DEFAULT_USD_RUB = Decimal("90.00")
USD_RUB_KEY = "usd_rub_rate"


async def get_usd_rub_rate(session) -> Decimal:
    value = await session.scalar(select(ShopSetting.value).where(ShopSetting.key == USD_RUB_KEY))
    try:
        rate = Decimal(str(value)) if value is not None else DEFAULT_USD_RUB
        if rate <= 0:
            raise ValueError
        return rate
    except Exception:
        return DEFAULT_USD_RUB


async def set_usd_rub_rate(session, rate: Decimal) -> None:
    if not rate.is_finite() or rate <= 0 or rate > Decimal("1000000"):
        raise ValueError("Курс должен быть положительным числом")
    setting = await session.get(ShopSetting, USD_RUB_KEY)
    if setting is None:
        session.add(ShopSetting(key=USD_RUB_KEY, value=str(rate.quantize(Decimal("0.0001")))))
    else:
        setting.value = str(rate.quantize(Decimal("0.0001")))
    await session.commit()


def rub_to_usd(amount_rub: Decimal | float | int, rate: Decimal) -> Decimal:
    amount = Decimal(str(amount_rub)) / rate
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def usd_to_rub(amount_usd: Decimal | float | int, rate: Decimal) -> Decimal:
    amount = Decimal(str(amount_usd)) * rate
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
