import httpx
from config.settings import settings


class PlategaError(RuntimeError):
    pass


class PlategaClient:
    def __init__(self):
        self.base_url = settings.platega_base_url.rstrip("/")

    def _headers(self):
        if not settings.platega_merchant_id or not settings.platega_secret:
            raise PlategaError("Platega credentials are not configured")
        return {
            "X-MerchantId": settings.platega_merchant_id,
            "X-Secret": settings.platega_secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_invoice(self, amount: float, currency: str, payload: str, description: str):
        body = {
            "paymentDetails": {"amount": round(float(amount), 2), "currency": currency},
            "description": description[:250],
            "payload": payload,
        }
        # Without paymentMethod Platega can show the methods enabled for this merchant.
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{self.base_url}/transaction/process",
                headers=self._headers(), json=body,
            )
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:500]}
        if response.is_error:
            raise PlategaError(f"Platega HTTP {response.status_code}: {data}")
        transaction_id = data.get("transactionId") or data.get("id")
        redirect_url = data.get("redirect") or data.get("paymentUrl") or data.get("url")
        if not transaction_id or not redirect_url:
            raise PlategaError(f"Unexpected Platega response schema: {data}")
        return {"external_id": str(transaction_id), "url": str(redirect_url), "raw": data}

    async def get_transaction(self, external_id: str):
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.base_url}/transaction/{external_id}", headers=self._headers()
            )
        response.raise_for_status()
        return response.json()
