from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
import logging
from config.settings import settings
from database.models.order import Order
from database.models.category import Category
from database.models.product import Product
from database.models.digital_key import DigitalKey
from database.models.user import User
from database.models.transaction import Transaction
from bot.keyboards.admin import admin_keyboard

router = Router()


class MarkupStates(StatesGroup):
    waiting_for_custom_markup = State()
log = logging.getLogger(__name__)

def is_admin(message):
    return message.from_user and message.from_user.id in settings.admins

@router.message(Command("admin"))
async def admin_help(message: Message):
    if not is_admin(message):
        return
    await message.answer(
        "<b>Панель администратора</b>\n"
        "Управление ценами, синхронизацией и заказами:",
        reply_markup=admin_keyboard(),
    )
    await message.answer(
        "<b>Дополнительные команды</b>\n"
        "/addcategory Название\n"
        "/addproduct CATEGORY_ID | Название | Цена | Описание\n"
        "/addkey PRODUCT_ID | CDK\n"
        "/products — список товаров\n"
        "/credit USER_ID СУММА\n"
        "/orders — последние заказы\n"
        "/syncsupplier — синхронизация каталога\n"
        "/setprice PRODUCT_ID ЦЕНА — ручная цена"
    )

@router.message(Command("addcategory"))
async def add_category(message: Message, session):
    if not is_admin(message): return
    name = message.text.partition(" ")[2].strip()
    if not name:
        await message.answer("Формат: /addcategory ChatGPT")
        return
    session.add(Category(name=name))
    await session.commit()
    await message.answer(f"Категория «{name}» создана.")

@router.message(Command("addproduct"))
async def add_product(message: Message, session):
    if not is_admin(message): return
    raw = message.text.partition(" ")[2]
    parts = [x.strip() for x in raw.split("|", 3)]
    if len(parts) < 3:
        await message.answer("Формат: /addproduct CATEGORY_ID | Название | Цена | Описание")
        return
    try:
        category_id, name, price = int(parts[0]), parts[1], float(parts[2].replace(",", "."))
        category = await session.get(Category, category_id)
        if not category or price <= 0: raise ValueError()
    except ValueError:
        await message.answer("Проверь ID категории и цену.")
        return
    product = Product(category_id=category_id, name=name, price=price,
                      description=parts[3] if len(parts) > 3 else "")
    session.add(product)
    await session.commit()
    await message.answer(f"Товар создан. ID: {product.id}")

@router.message(Command("products"))
async def list_products(message: Message, session):
    """Show local product IDs to admins, so /addkey never relies on guessed IDs."""
    if not is_admin(message):
        return
    rows = (await session.scalars(select(Product).order_by(Product.id))).all()
    if not rows:
        await message.answer("В базе пока нет товаров.")
        return
    lines = ["<b>Товары в базе:</b>"]
    for product in rows[:50]:
        lines.append(
            f"ID: <code>{product.id}</code> — {product.name} "
            f"({product.price:.2f} ₽; {'активен' if product.is_active else 'выключен'})"
        )
    await message.answer("\n".join(lines))


@router.message(Command("addkey"))
async def add_key(message: Message, session):
    if not is_admin(message):
        return
    raw = (message.text or "").partition(" ")[2]
    parts = [part.strip() for part in raw.split("|", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        await message.answer("Формат: /addkey PRODUCT_ID | CDK\nПример: /addkey 7 | XXXX-YYYY")
        return
    try:
        product_id = int(parts[0])
        if product_id <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Некорректный ID товара. Используй /products, чтобы посмотреть ID.")
        return

    # Use an explicit SELECT rather than relying only on the identity-map get().
    product = await session.scalar(select(Product).where(Product.id == product_id))
    if product is None:
        database_name = await session.scalar(select(text("current_database()")))
        log.warning(
            "Admin %s tried to add a key for missing product_id=%s in database=%s",
            message.from_user.id, product_id, database_name
        )
        await message.answer(
            f"Товар с ID {product_id} не найден в базе бота.\n"
            "Отправь /products, чтобы увидеть доступные ID.\n"
            "Если товар там есть, значит бот подключён к другой базе или запущена старая копия."
        )
        return

    try:
        session.add(DigitalKey(product_id=product_id, code=parts[1], status="AVAILABLE"))
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await message.answer("Этот CDK уже добавлен в базу. Повторно использовать его нельзя.")
        return
    except Exception:
        await session.rollback()
        log.exception("Failed to add digital key for product_id=%s", product_id)
        await message.answer("Не удалось сохранить CDK из-за ошибки базы. Проверь журнал бота.")
        return
    await message.answer(f"CDK успешно добавлен на склад товара «{product.name}» (ID: {product.id}).")

@router.message(Command("credit"))
async def credit_user(message: Message, session):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Формат: /credit USER_ID СУММА")
        return
    try:
        telegram_id, amount = int(parts[1]), float(parts[2].replace(",", "."))
        if amount <= 0: raise ValueError()
    except ValueError:
        await message.answer("Проверьте ID и сумму.")
        return
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
    if not user:
        await message.answer("Пользователь не найден.")
        return
    user.balance += amount
    session.add(Transaction(user_id=user.id, amount=amount, type="TOPUP",
                            description="Пополнение баланса администратором"))
    await session.commit()
    await message.answer(f"Начислено {amount:.2f} ₽ пользователю {telegram_id}.")

@router.message(Command("orders"))
async def orders(message: Message, session):
    if not is_admin(message): return
    rows = (await session.scalars(select(Order).order_by(Order.created_at.desc()).limit(15))).all()
    if not rows:
        await message.answer("Заказов пока нет.")
        return
    await message.answer("\n".join(
        f"#{o.id} | user={o.user_id} | {o.price:.2f} ₽ | {o.status}" for o in rows
    ))


@router.message(Command("linksupplier"))
async def link_supplier(message: Message, session):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Формат: /linksupplier PRODUCT_ID SUPPLIER_PRODUCT_ID")
        return
    try:
        local_id, supplier_id = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("ID должны быть числами.")
        return
    product = await session.get(Product, local_id)
    if not product:
        await message.answer("Локальный товар не найден.")
        return
    product.supplier_name = "sandromania"
    product.supplier_product_id = supplier_id
    await session.commit()
    await message.answer(
        f"Товар {product.name} связан с Sandromania product_id={supplier_id}. "
        "При отсутствии локального CDK бот сможет запросить закупку у поставщика."
    )

@router.message(Command("supplierbalance"))
async def supplier_balance(message: Message):
    if not is_admin(message): return
    from suppliers.sandromania.client import SandromaniaClient
    try:
        result = await SandromaniaClient().get_balance()
        await message.answer(f"<b>Баланс Sandromania</b>\n<pre>{str(result)[:3500]}</pre>")
    except Exception as exc:
        await message.answer(f"Не удалось получить баланс: {str(exc)[:800]}")


@router.message(Command("setprice"))
async def set_retail_price(message: Message, session):
    if not is_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Формат: /setprice PRODUCT_ID ЦЕНА")
        return
    try:
        product_id = int(parts[1])
        price = float(parts[2].replace(",", "."))
        if product_id <= 0 or price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Укажи корректный ID и цену больше нуля.")
        return
    product = await session.get(Product, product_id)
    if not product:
        await message.answer("Товар не найден. Используй /products.")
        return
    product.price = price
    product.is_active = True
    await session.commit()
    await message.answer(
        f"Розничная цена товара «{product.name}» установлена: {price:.2f} ₽. "
        "Товар активирован."
    )



@router.message(Command("setmarkup"))
async def set_markup(message: Message, session):
    if not is_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Формат: /setmarkup 30")
        return
    try:
        markup = float(parts[1].replace(",", "."))
        if not 0 <= markup <= 500:
            raise ValueError
    except ValueError:
        await message.answer("Укажи наценку от 0 до 500 процентов.")
        return

    rows = (await session.scalars(
        select(Product).where(
            Product.supplier_name == "sandromania",
            Product.supplier_product_id.is_not(None),
            Product.supplier_cost.is_not(None),
        )
    )).all()
    changed = 0
    for product in rows:
        product.markup_percent = markup
        product.price = round(product.supplier_cost * (1 + markup / 100), 2)
        # Keep products visible in catalogue if already published; availability is
        # checked separately and blocks checkout when stock is zero or unknown.
        if product.supplier_available and (product.supplier_stock is None or product.supplier_stock > 0):
            product.is_active = True
        changed += 1
    await session.commit()
    await message.answer(
        f"✅ Наценка {markup:g}% установлена.\n"
        f"Пересчитано товаров: {changed}.\n"
        "Розничная цена теперь рассчитывается от актуальной закупочной цены. "
        "При следующей синхронизации она обновится автоматически."
    )

@router.message(Command("syncsupplier"))
async def sync_supplier(message: Message, session):
    if not is_admin(message):
        return
    await message.answer("⏳ Запрашиваю каталог Sandromania и синхронизирую товары...")
    try:
        from services.supplier_sync import sync_sandromania_catalog
        result = await sync_sandromania_catalog(session)
        await message.answer(
            "<b>Синхронизация завершена</b>\n"
            f"Получено от поставщика: {result['received']}\n"
            f"Добавлено новых: {result['created']}\n"
            f"Обновлено: {result['updated']}\n"
            f"Пропущено из-за неполных данных: {result['skipped']}\n"
            f"Недоступно у поставщика: {result['unavailable']}\n\n"
            "Новые товары импортируются выключенными с ценой 0 ₽. "
            "Установи розничную цену командой /setprice PRODUCT_ID ЦЕНА."
        )
    except Exception as exc:
        await session.rollback()
        log.exception("Sandromania catalog sync failed")
        await message.answer(f"Не удалось синхронизировать каталог: {str(exc)[:700]}")


@router.message(Command("supplierproducts"))
async def supplier_products(message: Message):
    if not is_admin(message):
        return
    await message.answer(
        "Для загрузки всех товаров в базу используй /syncsupplier. "
        "Сырые ответы API больше не выводятся в чат."
    )


# ---------- Интерактивная панель управления наценкой ----------

def _is_admin_callback(callback: CallbackQuery) -> bool:
    return bool(callback.from_user and callback.from_user.id in settings.admins)


async def _current_markup(session) -> float:
    value = await session.scalar(
        select(Product.markup_percent)
        .where(
            Product.supplier_name == "sandromania",
            Product.supplier_product_id.is_not(None),
            Product.supplier_cost.is_not(None),
        )
        .order_by(Product.id)
        .limit(1)
    )
    return float(value if value is not None else 30.0)


def _markup_preview_keyboard(markup: float):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Применить", callback_data=f"admin:markup:apply:{markup:g}")
    kb.button(text="↩️ Назад к ценам", callback_data="admin:prices")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "admin:prices")
async def admin_prices(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    markup = await _current_markup(session)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="−5%", callback_data="admin:markup:delta:-5")
    kb.button(text="−1%", callback_data="admin:markup:delta:-1")
    kb.button(text=f"Текущая: {markup:g}%", callback_data="admin:prices")
    kb.button(text="+1%", callback_data="admin:markup:delta:1")
    kb.button(text="+5%", callback_data="admin:markup:delta:5")
    kb.button(text="✏️ Ввести свой процент", callback_data="admin:markup:custom")
    kb.button(text="🔄 Синхронизировать цены", callback_data="admin:sync")
    kb.button(text="⬅️ В меню", callback_data="admin:home")
    kb.adjust(2, 1, 2, 1, 1, 1)
    await callback.message.edit_text(
        "<b>💰 Управление ценами</b>\n"
        f"Текущая наценка: <b>{markup:g}%</b>\n"
        "Изменение применяется ко всем товарам Sandromania, у которых известна закупочная цена.",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:markup:delta:"))
async def admin_markup_delta(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        delta = float(callback.data.rsplit(":", 1)[1])
        markup = max(0.0, min(500.0, await _current_markup(session) + delta))
    except (ValueError, IndexError):
        await callback.answer("Некорректное значение", show_alert=True)
        return
    rows = (await session.scalars(
        select(Product).where(
            Product.supplier_name == "sandromania",
            Product.supplier_product_id.is_not(None),
            Product.supplier_cost.is_not(None),
        ).order_by(Product.id)
    )).all()
    if not rows:
        await callback.answer("Нет товаров с сохранённой закупочной ценой", show_alert=True)
        return
    samples = [
        f"• {p.name[:45]}: {p.supplier_cost:.2f} ₽ → {p.supplier_cost * (1 + markup / 100):.2f} ₽"
        for p in rows[:5]
    ]
    await callback.message.edit_text(
        f"<b>Предпросмотр наценки {markup:g}%</b>\n"
        f"Будет пересчитано товаров: <b>{len(rows)}</b>\n\n"
        + "\n".join(samples)
        + ("\n…" if len(rows) > 5 else "")
        + "\n\nПодтвердить изменение?",
        reply_markup=_markup_preview_keyboard(markup),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:markup:custom")
async def admin_markup_custom(callback: CallbackQuery, state: FSMContext):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(MarkupStates.waiting_for_custom_markup)
    await callback.message.answer("Введи новую наценку от 0 до 500%. Например: 35")
    await callback.answer()


@router.message(MarkupStates.waiting_for_custom_markup)
async def admin_markup_custom_value(message: Message, state: FSMContext, session):
    if not is_admin(message):
        await state.clear()
        return
    raw = (message.text or "").strip().replace(",", ".").replace("%", "")
    try:
        markup = float(raw)
        if not 0 <= markup <= 500:
            raise ValueError
    except ValueError:
        await message.answer("Введи число от 0 до 500. Например: 35")
        return
    await state.clear()
    rows = (await session.scalars(
        select(Product).where(
            Product.supplier_name == "sandromania",
            Product.supplier_product_id.is_not(None),
            Product.supplier_cost.is_not(None),
        ).order_by(Product.id)
    )).all()
    if not rows:
        await message.answer("Нет товаров с сохранённой закупочной ценой. Сначала выполни синхронизацию поставщика.")
        return
    samples = [
        f"• {p.name[:45]}: {p.supplier_cost:.2f} ₽ → {p.supplier_cost * (1 + markup / 100):.2f} ₽"
        for p in rows[:5]
    ]
    await message.answer(
        f"<b>Предпросмотр наценки {markup:g}%</b>\n"
        f"Будет пересчитано товаров: <b>{len(rows)}</b>\n\n"
        + "\n".join(samples)
        + ("\n…" if len(rows) > 5 else "")
        + "\n\nПодтвердить изменение?",
        reply_markup=_markup_preview_keyboard(markup),
    )


@router.callback_query(F.data.startswith("admin:markup:apply:"))
async def admin_markup_apply(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        markup = float(callback.data.rsplit(":", 1)[1])
        if not 0 <= markup <= 500:
            raise ValueError
    except ValueError:
        await callback.answer("Некорректная наценка", show_alert=True)
        return
    rows = (await session.scalars(
        select(Product).where(
            Product.supplier_name == "sandromania",
            Product.supplier_product_id.is_not(None),
            Product.supplier_cost.is_not(None),
        )
    )).all()
    for product in rows:
        product.markup_percent = markup
        product.price = round(float(product.supplier_cost) * (1 + markup / 100), 2)
        if product.supplier_available and (product.supplier_stock is None or product.supplier_stock > 0):
            product.is_active = True
    await session.commit()
    await callback.message.edit_text(
        f"✅ Наценка <b>{markup:g}%</b> установлена.\n"
        f"Пересчитано товаров: <b>{len(rows)}</b>.",
        reply_markup=admin_keyboard(),
    )
    await callback.answer("Цены обновлены")


@router.callback_query(F.data == "admin:sync")
async def admin_sync_callback(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Запускаю синхронизацию…")
    await callback.message.answer("⏳ Синхронизирую каталог Sandromania…")
    try:
        from services.supplier_sync import sync_sandromania_catalog
        result = await sync_sandromania_catalog(session)
        await callback.message.answer(
            "<b>Синхронизация завершена</b>\n"
            f"Получено: {result['received']}\n"
            f"Добавлено: {result['created']}\n"
            f"Обновлено: {result['updated']}\n"
            f"Пропущено: {result['skipped']}\n"
            f"Недоступно: {result['unavailable']}"
        )
    except Exception as exc:
        await session.rollback()
        log.exception("Sandromania catalog sync from admin panel failed")
        await callback.message.answer(f"Не удалось синхронизировать каталог: {str(exc)[:500]}")


@router.callback_query(F.data == "admin:home")
async def admin_home(callback: CallbackQuery):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "<b>Панель администратора</b>\nВыбери нужный раздел:",
        reply_markup=admin_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:orders")
async def admin_orders_callback(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rows = (await session.scalars(
        select(Order).order_by(Order.created_at.desc()).limit(15)
    )).all()
    if not rows:
        await callback.message.answer("Заказов пока нет.")
    else:
        await callback.message.answer("\n".join(
            f"#{o.id} | user={o.user_id} | {o.price:.2f} ₽ | {o.status}" for o in rows
        ))
    await callback.answer()
