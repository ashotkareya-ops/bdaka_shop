from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.category import Category
from database.models.product import Product
from suppliers.sandromania.client import SandromaniaClient


class CatalogFormatError(RuntimeError):
    pass


def _first(data: dict, names: tuple[str, ...], default=None):
    for name in names:
        value = data.get(name)
        if value not in (None, ""):
            return value
    return default


def _as_number(value, *, integer=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", ".").replace(" ", ""))
        if result < 0:
            return None
        return int(result) if integer else result
    except (TypeError, ValueError):
        return None


def _unwrap_catalog(payload: Any) -> list[dict]:
    """Accept common list wrappers; fail closed if provider schema is unfamiliar."""
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = None
        for key in ("products", "items", "data", "results", "catalog"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
            if isinstance(value, dict):
                for nested in ("products", "items", "results"):
                    if isinstance(value.get(nested), list):
                        rows = value[nested]
                        break
                if rows is not None:
                    break
        if rows is None:
            raise CatalogFormatError(
                "Ответ API не содержит узнаваемый список товаров "
                "(products/items/data/results/catalog). Сверьте формат ответа с документацией поставщика."
            )
    else:
        raise CatalogFormatError("Неожиданный формат каталога поставщика.")

    normalized = [row for row in rows if isinstance(row, dict)]
    if rows and not normalized:
        raise CatalogFormatError("В списке поставщика нет объектов товаров.")
    return normalized


def _normalize(row: dict) -> dict | None:
    raw_id = _first(row, ("product_id", "id", "sku_id"))
    name = _first(row, ("name", "title", "product_name"))
    if raw_id is None or not name or not str(raw_id).isdigit():
        return None

    cost = _as_number(_first(row, ("price_rub", "price", "cost", "supplier_price", "amount")))
    stock = _as_number(
        _first(row, ("stock", "quantity", "available_quantity", "balance", "in_stock")),
        integer=True,
    )
    status_raw = str(_first(row, ("status", "state"), "")).strip().lower()
    explicit_available = _first(row, ("available", "is_available", "active", "is_active"))
    if isinstance(explicit_available, str):
        explicit_available = explicit_available.lower() in {"1", "true", "yes", "active", "available"}
    if explicit_available is None:
        explicit_available = status_raw not in {"disabled", "inactive", "unavailable", "out_of_stock", "hidden"}
    if stock is not None and stock <= 0:
        explicit_available = False

    category_value = _first(row, ("category_name", "category", "group", "type"), "Sandromania")
    if isinstance(category_value, dict):
        category_value = _first(category_value, ("name", "title"), "Sandromania")
    category_name = str(category_value or "Sandromania").strip()[:120] or "Sandromania"

    description = _first(row, ("description", "details", "comment"), "")
    if isinstance(description, (dict, list)):
        description = ""
    return {
        "supplier_product_id": int(raw_id),
        "name": str(name).strip()[:180],
        "description": str(description or "")[:10000],
        "supplier_cost": cost,
        "supplier_stock": stock,
        "supplier_available": bool(explicit_available),
        "category_name": category_name,
    }


async def sync_sandromania_catalog(session: AsyncSession) -> dict:
    payload = await SandromaniaClient().get_products()
    rows = _unwrap_catalog(payload)
    if not rows:
        return {"received": 0, "created": 0, "updated": 0, "skipped": 0, "unavailable": 0}

    created = updated = skipped = unavailable = 0
    now = datetime.utcnow()

    for raw in rows:
        item = _normalize(raw)
        if not item:
            skipped += 1
            continue

        category = await session.scalar(
            select(Category).where(Category.name == item["category_name"])
        )
        if category is None:
            category = Category(name=item["category_name"], is_active=True)
            session.add(category)
            await session.flush()

        product = await session.scalar(
            select(Product).where(
                Product.supplier_name == "sandromania",
                Product.supplier_product_id == item["supplier_product_id"],
            )
        )
        if product is None:
            # Do not silently sell at supplier cost. New imports start inactive
            # until the admin sets a retail price with /setprice.
            product = Product(
                category_id=category.id,
                name=item["name"],
                price=round(item["supplier_cost"] * 1.30, 2) if item["supplier_cost"] is not None else 0.0,
                description=item["description"],
                is_active=bool(item["supplier_available"] and item["supplier_stock"] and item["supplier_stock"] > 0 and item["supplier_cost"] is not None),
                markup_percent=30.0,
                supplier_name="sandromania",
                supplier_product_id=item["supplier_product_id"],
                supplier_cost=item["supplier_cost"],
                supplier_stock=item["supplier_stock"],
                supplier_available=item["supplier_available"],
                supplier_synced_at=now,
            )
            session.add(product)
            created += 1
        else:
            product.category_id = category.id
            product.name = item["name"]
            # Keep the description once populated: admins can customize it and
            # routine supplier sync must not overwrite their shop copy.
            if not (product.description or "").strip():
                product.description = item["description"]
            product.supplier_cost = item["supplier_cost"]
            if item["supplier_cost"] is not None:
                product.price = round(item["supplier_cost"] * (1 + (product.markup_percent or 30.0) / 100), 2)
            product.supplier_stock = item["supplier_stock"]
            product.supplier_available = item["supplier_available"]
            product.supplier_synced_at = now
            # Preserve admin retail price and active/inactive choice.
            updated += 1

        if not item["supplier_available"]:
            unavailable += 1

    await session.commit()
    return {
        "received": len(rows),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "unavailable": unavailable,
    }


async def refresh_supplier_product_stock(session: AsyncSession, product: Product) -> dict | None:
    """Refresh one mapped product from the provider catalog immediately before checkout."""
    if product.supplier_name != "sandromania" or not product.supplier_product_id:
        return None
    payload = await SandromaniaClient().get_products()
    for raw in _unwrap_catalog(payload):
        item = _normalize(raw)
        if item and str(item["supplier_product_id"]) == str(product.supplier_product_id):
            product.supplier_cost = item["supplier_cost"]
            if item["supplier_cost"] is not None:
                product.price = round(item["supplier_cost"] * (1 + (product.markup_percent or 30.0) / 100), 2)
            product.supplier_stock = item["supplier_stock"]
            product.supplier_available = item["supplier_available"]
            product.supplier_synced_at = datetime.utcnow()
            await session.commit()
            return item
    # A mapped product missing from the current provider feed is treated as unavailable.
    product.supplier_available = False
    product.supplier_stock = 0
    product.supplier_synced_at = datetime.utcnow()
    await session.commit()
    return None
