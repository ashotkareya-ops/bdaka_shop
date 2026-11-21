from decimal import Decimal, ROUND_HALF_UP
from services.exchange_rate import get_usd_rub_rate

SUPPORTED_CURRENCIES = {"RUB", "USD"}

def normalize_currency(value: str | None) -> str:
    value = (value or "RUB").upper()
    return value if value in SUPPORTED_CURRENCIES else "RUB"

async def format_user_balance(session, amount_rub: float, currency: str) -> str:
    currency = normalize_currency(currency)
    amount = Decimal(str(amount_rub))
    if currency == "USD":
        rate = await get_usd_rub_rate(session)
        converted = (amount / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"${converted:,.2f} USD"
    return f"{amount:,.2f} ₽ RUB"

async def currency_rate_line(session) -> str:
    rate = await get_usd_rub_rate(session)
    return f"Курс магазина: 1 USD = {rate:.4f} RUB"
