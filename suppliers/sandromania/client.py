import asyncio
import json
from urllib.parse import quote, urlparse

import httpx

from config.settings import settings
from suppliers.sandromania.auth import build_headers


class SandromaniaAPIError(RuntimeError):
    pass


def _find_value(data, names):
    """Find a non-empty value by key in nested provider responses."""
    wanted = {name.lower() for name in names}
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() in wanted and value not in (None, ""):
                return value
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


def _find_delivery(data):
    """
    Return a delivered CDK or activation URL.
    Only treats URLs as deliverables when their field name indicates delivery,
    activation, redemption, a link, or a key. This avoids returning API/help URLs.
    """
    code_names = (
        "cdk", "code", "key", "activation_code", "license_key",
        "license", "serial", "serial_key",
    )
    link_names = (
        "activation_url", "activation_link", "redeem_url", "redeem_link",
        "delivery_url", "delivery_link", "download_url", "product_url",
        "link", "url",
    )

    value = _find_value(data, code_names)
    if value not in (None, "") and not isinstance(value, (dict, list)):
        return str(value), "code"

    def walk(obj):
        if isinstance(obj, dict):
            for key, item in obj.items():
                key_name = str(key).lower()
                if any(word in key_name for word in (
                    "activation", "redeem", "delivery", "download", "link", "url"
                )):
                    if isinstance(item, str) and item.strip().startswith(("https://", "http://")):
                        parsed = urlparse(item.strip())
                        if parsed.scheme in ("http", "https") and parsed.netloc:
                            return item.strip(), "link"
                found = walk(item)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = walk(item)
                if found:
                    return found
        return None

    found = walk(data)
    if found:
        return found

    # Some APIs return a generic "result" or "data" string containing the URL.
    # Do not scan arbitrary strings: that could accidentally expose unrelated links.
    return None



def _find_deliveries(data):
    """Collect distinct delivery codes/links from a supplier response."""
    code_names = {"cdk", "code", "key", "activation_code", "license_key", "license", "serial", "serial_key"}
    link_names = {"activation_url", "activation_link", "redeem_url", "redeem_link", "delivery_url", "delivery_link", "download_url", "product_url", "link", "url"}
    found = []
    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_name = str(key).lower()
                if key_name in code_names:
                    values = value if isinstance(value, list) else [value]
                    for item in values:
                        if isinstance(item, (str, int)) and str(item).strip():
                            found.append(str(item).strip())
                elif key_name in link_names:
                    values = value if isinstance(value, list) else [value]
                    for item in values:
                        if isinstance(item, str) and item.strip().startswith(("https://", "http://")):
                            found.append(item.strip())
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    walk(data)
    return list(dict.fromkeys(found))


def _find_status(data):
    value = _find_value(data, ("status", "state", "order_status"))
    return str(value or "").strip().lower()


def _find_order_id(data):
    value = _find_value(data, ("order_id", "orderId", "id"))
    return str(value) if value not in (None, "") else None


class SandromaniaClient:
    """Partner API client using the configured signed-request contract."""

    def __init__(self):
        self.base_url = settings.sandromania_base_url.rstrip("/")
        self.api_key = settings.sandromania_api_key
        self.api_secret = settings.sandromania_api_secret
        self.timeout = 20.0

    def _require_credentials(self):
        if not self.api_key or not self.api_secret:
            raise SandromaniaAPIError(
                "Sandromania API credentials are not configured in .env"
            )

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
            # Avoid printing credentials or full activation links in exception messages.
            raise SandromaniaAPIError(
                f"Sandromania HTTP {response.status_code}: response received"
            )
        if isinstance(data, dict) and data.get("ok") is False:
            raise SandromaniaAPIError("Sandromania API returned ok=false")
        return data

    async def health(self):
        return await self._request("GET", "/api/v1/health")

    async def get_products(self):
        return await self._request("GET", "/api/v1/products")

    async def get_balance(self):
        return await self._request("GET", "/api/v1/balance")

    async def get_balance_rub(self) -> float:
        """Return supplier balance in RUB; reject unknown currency/response shapes."""
        data = await self.get_balance()
        if not isinstance(data, dict):
            raise SandromaniaAPIError("Unexpected Sandromania balance response")
        currency = _find_value(data, ("currency", "asset"))
        amount = _find_value(data, ("balance", "available_balance", "amount", "available"))
        if amount is None:
            raise SandromaniaAPIError("Balance amount is missing in Sandromania response")
        if currency and str(currency).upper() not in {"RUB", "RUR"}:
            raise SandromaniaAPIError(f"Unsupported supplier balance currency: {currency}")
        try:
            return float(amount)
        except (TypeError, ValueError) as exc:
            raise SandromaniaAPIError("Invalid supplier balance amount") from exc

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
        path = f"/api/v1/orders/{quote(str(order_id), safe='')}"
        return await self._request("GET", path)

    async def purchase_and_wait(self, supplier_product_id: int, idempotency_key: str, quantity: int = 1):
        created = await self.create_order(supplier_product_id, quantity, idempotency_key)

        order_id = _find_order_id(created)
        delivery = _find_delivery(created)
        deliveries = _find_deliveries(created)
        status = _find_status(created)

        if delivery or len(deliveries) >= quantity:
            first_delivery = delivery[0] if delivery else deliveries[0]
            return {
                "order_id": order_id or "",
                "status": "completed",
                "code": first_delivery,
                "delivery": first_delivery,
                "deliveries": deliveries or [first_delivery],
                "delivery_type": delivery[1] if delivery else "code",
                "raw": created,
            }

        if not order_id:
            raise SandromaniaAPIError(
                "Purchase response did not contain an order ID or a delivery item"
            )

        current = created
        success_statuses = {
            "completed", "complete", "success", "successful",
            "done", "fulfilled", "paid", "finished",
        }
        failure_statuses = {
            "failed", "error", "cancelled", "canceled", "rejected",
        }

        for attempt in range(settings.sandromania_poll_attempts):
            if status in failure_statuses:
                raise SandromaniaAPIError(
                    f"Supplier order {order_id} has failure status: {status}"
                )

            # A completed status without a delivery item is not enough to send a
            # fabricated code. Fetch the final order payload once more if possible.
            if attempt > 0 or status not in success_statuses:
                await asyncio.sleep(settings.sandromania_poll_interval)

            current = await self.get_order(order_id)
            delivery = _find_delivery(current)
            deliveries = _find_deliveries(current)
            status = _find_status(current) or status

            if delivery or len(deliveries) >= quantity:
                first_delivery = delivery[0] if delivery else deliveries[0]
                return {
                    "order_id": order_id,
                    "status": "completed",
                    "code": first_delivery,
                    "delivery": first_delivery,
                    "deliveries": deliveries or [first_delivery],
                    "delivery_type": delivery[1] if delivery else "code",
                    "raw": current,
                }

            if status in failure_statuses:
                raise SandromaniaAPIError(
                    f"Supplier order {order_id} has failure status: {status}"
                )

            # If provider says completed but has no recognized delivery field,
            # keep the order pending manual reconciliation instead of guessing.
            if status in success_statuses:
                break

        return {
            "order_id": order_id,
            "status": "processing",
            "code": None,
            "delivery": None,
            "delivery_type": None,
            "provider_status": status,
            "raw": current,
        }
