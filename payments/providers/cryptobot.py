import hashlib
import hmac

import httpx

from config.settings import settings


class CryptoBotError(Exception):
    pass


def verify_webhook_signature(token: str, raw_body: bytes, signature: str) -> bool:
    """Crypto Pay signs webhooks: HMAC-SHA256(key=SHA256(app_token), msg=raw body), hex."""
    if not token or not signature:
        return False
    secret = hashlib.sha256(token.encode("utf-8")).digest()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


class CryptoBotClient:
    def __init__(self, token: str | None = None, testnet: bool | None = None):
        self.token = token if token is not None else settings.crypto_pay_token
        is_testnet = testnet if testnet is not None else settings.crypto_pay_testnet
        self.base_url = (
            "https://testnet-pay.crypt.bot/api"
            if is_testnet
            else "https://pay.crypt.bot/api"
        )

    async def _request(self, method: str, payload: dict | None = None) -> dict | list:
        if not self.token:
            raise CryptoBotError("CRYPTO_PAY_TOKEN is not configured")
        headers = {"Crypto-Pay-API-Token": self.token}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self.base_url}/{method}", json=payload or {}, headers=headers
            )
        try:
            data = resp.json()
        except ValueError:
            raise CryptoBotError(f"Crypto Pay HTTP {resp.status_code}: non-JSON response")
        if resp.is_error or not data.get("ok"):
            # Error body contains only an error name/code, never the token.
            raise CryptoBotError(f"Crypto Pay error on {method}: {data.get('error') or resp.status_code}")
        return data["result"]

    async def create_invoice(
        self,
        amount: float | str,
        *,
        fiat: str | None = None,
        asset: str | None = None,
        accepted_assets: list[str] | None = None,
        description: str | None = None,
        payload: str | None = None,
        expires_in: int | None = None,
    ) -> dict:
        """
        Fiat mode (fiat="RUB"): the buyer is shown the amount in RUB and picks any
        accepted crypto asset; Crypto Pay converts at its own rate.
        Crypto mode (asset="USDT"): the amount is in that asset.
        """
        params: dict = {"amount": f"{float(amount):.2f}" if fiat else str(amount)}
        if fiat:
            params["currency_type"] = "fiat"
            params["fiat"] = fiat.upper()
            if accepted_assets:
                params["accepted_assets"] = ",".join(accepted_assets)
        else:
            params["currency_type"] = "crypto"
            params["asset"] = asset or "USDT"
        if description:
            params["description"] = description[:1000]
        if payload:
            params["payload"] = payload
        if expires_in:
            params["expires_in"] = int(expires_in)
        params["allow_comments"] = False
        params["allow_anonymous"] = False
        return await self._request("createInvoice", params)

    async def get_invoices(self, invoice_ids: list[int | str]) -> list[dict]:
        if not invoice_ids:
            return []
        result = await self._request(
            "getInvoices",
            {"invoice_ids": ",".join(str(i) for i in invoice_ids), "count": 1000},
        )
        # Newer API versions wrap the list in {"items": [...]}, older ones return it directly.
        if isinstance(result, dict):
            return list(result.get("items") or [])
        return list(result or [])

    async def get_invoice(self, invoice_id: int | str) -> dict | None:
        items = await self.get_invoices([invoice_id])
        return items[0] if items else None

    async def get_rate(self, source: str, target: str) -> float:
        rates = await self._request("getExchangeRates")
        for item in rates or []:
            if (
                str(item.get("source", "")).upper() == source.upper()
                and str(item.get("target", "")).upper() == target.upper()
                and item.get("is_valid", True)
            ):
                return float(item["rate"])
        raise CryptoBotError(f"No exchange rate {source}->{target}")

    async def get_me(self) -> dict:
        return await self._request("getMe")

    async def transfer(
        self,
        user_id: int,
        amount: float | str,
        spend_id: str,
        asset: str = "USDT",
        comment: str | None = None,
    ) -> dict:
        params: dict = {
            "user_id": int(user_id),
            "asset": asset,
            "amount": str(amount),
            "spend_id": spend_id,
        }
        if comment:
            params["comment"] = comment
        return await self._request("transfer", params)


async def get_usd_rub_rate() -> float:
    """1 USD (= 1 USDT) in RUB: fixed from .env if set, otherwise live from Crypto Pay."""
    if settings.crypto_usd_rub_rate > 0:
        return float(settings.crypto_usd_rub_rate)
    return await CryptoBotClient().get_rate("USDT", "RUB")
