import json
import asyncio
import uuid
import httpx
from config.settings import settings
from suppliers.sandromania.auth import build_headers

class SandromaniaAPIError(RuntimeError):
    pass

class SandromaniaClient:
    """Partner API client using the provider's documented HMAC contract."""

    def __init__(self):
        self.base_url = settings.sandromania_base_url.rstrip("/")
        self.api_key = settings.sandromania_api_key
        self.api_secret = settings.sandromania_api_secret
        self.timeout = 20.0

    def _require_credentials(self):
        if not self.api_key or not self.api_secret:
            raise SandromaniaAPIError("Sandromania API credentials are not configured in .env")

    async def _request(self, method: str, path: str, payload=None, idempotency_key=None):
        self._require_credentials()
        body = b"" if payload is None else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        headers = build_headers(self.api_key, self.api_secret, method, path, body)
        headers["Accept"] = "application/json"
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.request(
                method.upper(), path, content=body, headers=headers
            )
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:1000]}
        if response.is_error:
            raise SandromaniaAPIError(
                f"Sandromania HTTP {response.status_code}: {str(data)[:1000]}"
            )
        if isinstance(data, dict) and data.get("ok") is False:
            raise SandromaniaAPIError(f"Sandromania API error: {str(data)[:1000]}")
        return data

    async def health(self):
        # Health endpoint may or may not require authentication; provider specifies signed requests.
        return await self._request("GET", "/api/v1/health")

    async def get_products(self):
        return await self._request("GET", "/api/v1/products")

    async def get_balance(self):
        return await self._request("GET", "/api/v1/balance")

    async def create_order(self, supplier_product_id: int, quantity: int, idempotency_key: str):
        if not 1 <= quantity <= 100:
            raise ValueError("quantity must be between 1 and 100")
        if not 16 <= len(idempotency_key) <= 120:
            raise ValueError("Idempotency-Key must contain 16-120 characters")
        payload = {"product_id": int(supplier_product_id), "quantity": int(quantity)}
        return await self._request(
            "POST", "/api/v1/orders", payload=payload,
            idempotency_key=idempotency_key
        )

    async def get_order(self, order_id: str):
        from urllib.parse import quote
        return await self._request("GET", f"/api/v1/orders/{quote(str(order_id), safe='')}")

    async def purchase_and_wait(self, supplier_product_id: int, idempotency_key: str):
        created = await self.create_order(supplier_product_id, 1, idempotency_key)
        order_id = _find_value(created, ("order_id", "id"))
        key = _find_value(created, ("cdk", "code", "key", "activation_code"))
        status = str(_find_value(created, ("status", "state")) or "").lower()

        if key:
            return {"order_id": str(order_id or ""), "status": "completed", "code": str(key), "raw": created}
        if not order_id:
            raise SandromaniaAPIError(
                "Purchase response did not contain order_id or a delivery code. "
                "Inspect the provider's documented response schema before enabling sales."
            )

        for _ in range(settings.sandromania_poll_attempts):
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise SandromaniaAPIError(f"Supplier order failed: {created}")
            await asyncio.sleep(settings.sandromania_poll_interval)
            current = await self.get_order(str(order_id))
            key = _find_value(current, ("cdk", "code", "key", "activation_code"))
            status = str(_find_value(current, ("status", "state")) or status).lower()
            if key:
                return {"order_id": str(order_id), "status": "completed", "code": str(key), "raw": current}
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise SandromaniaAPIError(f"Supplier order failed: {current}")
        return {"order_id": str(order_id), "status": "processing", "code": None, "raw": current}

def _find_value(data, names):
    """Search common response wrappers without assuming one undocumented schema."""
    if isinstance(data, dict):
        for name in names:
            if data.get(name) not in (None, ""):
                return data[name]
        for value in data.values():
            found = _find_value(value, names)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_value(value, names)
            if found not in (None, ""):
                return found
    return None
