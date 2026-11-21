from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, text, delete, func
from sqlalchemy.exc import IntegrityError
import logging
from html import escape
from config.settings import settings
from database.models.order import Order
from database.models.category import Category
from database.models.product import Product
from database.models.digital_key import DigitalKey
from database.models.user import User
from database.models.transaction import Transaction
from database.models.payment import Payment
from bot.keyboards.admin import admin_keyboard

router = Router()


class MarkupStates(StatesGroup):
    waiting_for_custom_markup = State()


class DescriptionStates(StatesGroup):
    waiting_for_description = State()


class CategoryStates(StatesGroup):
    waiting_for_new_name = State()
    waiting_for_rename = State()
log = logging.getLogger(__name__)

def is_admin(message):
    return message.from_user and message.from_user.id in settings.admins


def _order_status_label(status: str) -> str:
    labels = {
        "COMPLETED": "✅ Успешно завершён — товар выдан",
        "PROCESSING": "⏳ Принят — ожидает завершения выдачи",
        "PAID": "💳 Оплата получена — выдача ожидается",
        "PENDING": "🕓 Ожидает оплаты",
        "FAILED": "❌ Ошибка сделки",
        "CANCELLED": "🚫 Отменён",
    }
    return labels.get(str(status).upper(), f"❔ {escape(str(status))}")


async def _get_detailed_orders(session, page: int = 1, page_size: int = 5):
    total = await session.scalar(select(func.count(Order.id))) or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * page_size

    rows = (await session.execute(
        select(Order, User, Product)
        .join(User, Order.user_id == User.id)
        .join(Product, Order.product_id == Product.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .offset(offset)
        .limit(page_size)
    )).all()

    if not rows:
        text = "📦 <b>Заказы</b>\n\nЗаказов пока нет."
    else:
        blocks = [f"📦 <b>Заказы · страница {page}/{total_pages}</b>"]
        for order, user, product in rows:
            if user.username:
                buyer = f"@{escape(user.username)}"
            elif user.full_name:
                buyer = escape(user.full_name)
            else:
                buyer = f"Пользователь {user.telegram_id}"

            payment = await session.scalar(
                select(Payment)
                .where(Payment.order_id == order.id)
                .order_by(Payment.created_at.desc())
                .limit(1)
            )
            if payment:
                provider_names = {
                    "platega": "Platega",
                    "manual": "Ручная оплата",
                }
                method = provider_names.get(
                    str(payment.provider).lower(),
                    escape(str(payment.provider or "Неизвестно"))
                )
                payment_status = str(payment.status or "UNKNOWN").upper()
                payment_result = {
                    "CONFIRMED": "оплата подтверждена",
                    "PAID": "оплата подтверждена",
                    "PENDING": "ожидает оплаты",
                    "FAILED": "платёж не прошёл",
                    "CANCELED": "платёж отменён",
                    "CANCELLED": "платёж отменён",
                }.get(payment_status, f"статус платежа: {escape(payment_status)}")
            else:
                method = "Внутренний баланс"
                payment_result = "списание с баланса магазина"

            created = (
                order.created_at.strftime("%d.%m.%Y %H:%M")
                if order.created_at else "не указана"
            )
            block = (
                f"\n\n<b>Заказ #{order.id}</b>\n"
                f"👤 Покупатель: {buyer}\n"
                f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
                f"🛍 Товар: <b>{escape(product.name)}</b>\n"
                f"💰 Сумма: <b>{order.price:.2f} ₽</b>\n"
                f"💳 Оплата: {method} — {payment_result}\n"
                f"📊 Сделка: {_order_status_label(order.status)}\n"
                f"🕒 Дата: {created}"
            )
            if order.supplier_order_id:
                block += f"\n🔗 Заказ поставщика: <code>{escape(str(order.supplier_order_id))}</code>"
            blocks.append(block)
        text = "".join(blocks)

    kb = InlineKeyboardBuilder()
    if page > 1:
        kb.button(text="⬅️ Назад", callback_data=f"admin:orders:page:{page - 1}")
    if page < total_pages:
        kb.button(text="Вперёд ➡️", callback_data=f"admin:orders:page:{page + 1}")
    kb.adjust(2)
    kb.button(text=f"📄 Страница {page}/{total_pages}", callback_data="admin:orders:current")
    kb.button(text="🔄 Обновить", callback_data=f"admin:orders:page:{page}")
    kb.adjust(2, 1)
    return text, kb.as_markup()



def _category_list_keyboard(categories):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for category, product_count in categories:
        status = "🟢" if category.is_active else "⚫"
        kb.button(
            text=f"{status} {category.name[:35]} · #{category.id} ({product_count})",
            callback_data=f"admin:category:manage:{category.id}",
        )
    kb.button(text="➕ Создать категорию", callback_data="admin:category:create")
    kb.button(text="⬅️ В меню", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


async def _category_rows(session):
    return (await session.execute(
        select(Category, func.count(Product.id))
        .outerjoin(Product, Product.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.name)
    )).all()


async def _show_categories(target, session, edit=False):
    rows = await _category_rows(session)
    if rows:
        text = (
            "📁 <b>Управление категориями</b>\n\n"
            "🟢 — категория включена\n"
            "⚫ — категория отключена\n"
            "В скобках указано количество товаров.\n\n"
            "Выбери категорию для управления:"
        )
    else:
        text = "📁 <b>Управление категориями</b>\n\nКатегорий пока нет."
    markup = _category_list_keyboard(rows)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


def _category_actions_keyboard(category, product_count):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Переименовать", callback_data=f"admin:category:rename:{category.id}")
    if category.is_active:
        kb.button(text="⏸ Отключить", callback_data=f"admin:category:toggle:{category.id}")
    else:
        kb.button(text="▶️ Включить", callback_data=f"admin:category:toggle:{category.id}")
    if product_count > 0:
        kb.button(text="📦 Перенести товары в другую категорию", callback_data=f"admin:category:move:from:{category.id}")
    else:
        kb.button(text="🗑 Удалить категорию", callback_data=f"admin:category:delete:{category.id}")
    kb.button(text="⬅️ К категориям", callback_data="admin:categories")
    kb.adjust(1)
    return kb.as_markup()


async def _show_category_detail(callback, session, category_id):
    category = await session.get(Category, category_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    count = await session.scalar(
        select(func.count(Product.id)).where(Product.category_id == category_id)
    ) or 0
    await callback.message.edit_text(
        f"📁 <b>{escape(category.name)}</b>\n"
        f"ID: <code>{category.id}</code>\n"
        f"Товаров: <b>{count}</b>\n"
        f"Статус: {'🟢 Включена' if category.is_active else '⚫ Отключена'}\n\n"
        "Выбери действие:",
        reply_markup=_category_actions_keyboard(category, count),
    )
    await callback.answer()


@router.message(Command("categories"))
async def categories_command(message: Message, session):
    if not is_admin(message):
        return
    await _show_categories(message, session)


@router.message(Command("deletecategory"))
async def delete_category_command(message: Message, session):
    if not is_admin(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /deletecategory ID\nСписок: /categories")
        return
    category_id = int(parts[1])
    category = await session.get(Category, category_id)
    if not category:
        await message.answer("Категория не найдена.")
        return
    count = await session.scalar(
        select(func.count(Product.id)).where(Product.category_id == category_id)
    ) or 0
    if count:
        await message.answer(
            f"Нельзя удалить «{escape(category.name)}»: в ней {count} товар(ов). "
            "Сначала перенеси или удали товары."
        )
        return
    name = category.name
    await session.delete(category)
    await session.commit()
    await message.answer(f"🗑 Категория «{escape(name)}» удалена.")


@router.callback_query(F.data == "admin:categories")
async def admin_categories(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _show_categories(callback, session)


@router.callback_query(F.data == "admin:category:create")
async def admin_category_create(callback: CallbackQuery, state: FSMContext):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(CategoryStates.waiting_for_new_name)
    await callback.message.answer(
        "➕ Отправь название новой категории отдельным сообщением.\n"
        "Для отмены используй /cancel."
    )
    await callback.answer()


@router.message(CategoryStates.waiting_for_new_name, Command("cancel"))
@router.message(CategoryStates.waiting_for_rename, Command("cancel"))
async def cancel_category_edit(message: Message, state: FSMContext):
    if not is_admin(message):
        await state.clear()
        return
    await state.clear()
    await message.answer("Действие с категорией отменено.")


@router.message(CategoryStates.waiting_for_new_name)
async def admin_category_create_save(message: Message, state: FSMContext, session):
    if not is_admin(message):
        return
    name = (message.text or "").strip()
    if not name or len(name) > 120 or name.startswith("/"):
        await message.answer("Название должно содержать от 1 до 120 символов. Попробуй ещё раз.")
        return
    exists = await session.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if exists:
        await message.answer("Категория с таким названием уже существует.")
        return
    session.add(Category(name=name, is_active=True))
    await session.commit()
    await state.clear()
    await message.answer(f"✅ Категория «{escape(name)}» создана.")
    await _show_categories(message, session)


@router.callback_query(F.data.startswith("admin:category:manage:"))
async def admin_category_manage(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        category_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    await _show_category_detail(callback, session, category_id)


@router.callback_query(F.data.startswith("admin:category:rename:"))
async def admin_category_rename(callback: CallbackQuery, state: FSMContext, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        category_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    category = await session.get(Category, category_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    await state.set_state(CategoryStates.waiting_for_rename)
    await state.update_data(rename_category_id=category_id)
    await callback.message.answer(
        f"✏️ Отправь новое название для категории «{escape(category.name)}».\n"
        "Для отмены используй /cancel."
    )
    await callback.answer()


@router.message(CategoryStates.waiting_for_rename)
async def admin_category_rename_save(message: Message, state: FSMContext, session):
    if not is_admin(message):
        return
    name = (message.text or "").strip()
    data = await state.get_data()
    category_id = data.get("rename_category_id")
    if not name or len(name) > 120 or name.startswith("/"):
        await message.answer("Название должно содержать от 1 до 120 символов. Попробуй ещё раз.")
        return
    category = await session.get(Category, category_id)
    if not category:
        await state.clear()
        await message.answer("Категория больше не существует.")
        return
    exists = await session.scalar(
        select(Category).where(func.lower(Category.name) == name.lower(), Category.id != category_id)
    )
    if exists:
        await message.answer("Другая категория уже использует это название.")
        return
    category.name = name
    await session.commit()
    await state.clear()
    await message.answer(f"✅ Название категории изменено на «{escape(name)}».")
    await _show_categories(message, session)


@router.callback_query(F.data.startswith("admin:category:toggle:"))
async def admin_category_toggle(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        category_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    category = await session.get(Category, category_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    category.is_active = not category.is_active
    await session.commit()
    await _show_category_detail(callback, session, category_id)


@router.callback_query(F.data.startswith("admin:category:move:from:"))
async def admin_category_move_from(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        source_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    source = await session.get(Category, source_id)
    if not source:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    targets = (await session.scalars(
        select(Category).where(Category.id != source_id).order_by(Category.name)
    )).all()
    if not targets:
        await callback.answer("Сначала создай другую категорию", show_alert=True)
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for target in targets:
        kb.button(
            text=f"{'🟢' if target.is_active else '⚫'} {target.name[:35]} · #{target.id}",
            callback_data=f"admin:category:move:choose:{source_id}:{target.id}",
        )
    kb.button(text="⬅️ Назад", callback_data=f"admin:category:manage:{source_id}")
    kb.adjust(1)
    await callback.message.edit_text(
        f"📦 Выбери категорию, куда перенести все товары из «{escape(source.name)}»:",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:category:move:choose:"))
async def admin_category_move_choose(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        _, _, _, _, source_id, target_id = callback.data.split(":")
        source_id, target_id = int(source_id), int(target_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректные категории", show_alert=True)
        return
    source = await session.get(Category, source_id)
    target = await session.get(Category, target_id)
    if not source or not target or source_id == target_id:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    count = await session.scalar(
        select(func.count(Product.id)).where(Product.category_id == source_id)
    ) or 0
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"✅ Перенести {count} товар(ов)",
        callback_data=f"admin:category:move:apply:{source_id}:{target_id}",
    )
    kb.button(text="↩️ Отмена", callback_data=f"admin:category:manage:{source_id}")
    kb.adjust(1)
    await callback.message.edit_text(
        f"Подтверди перенос всех товаров из «{escape(source.name)}» "
        f"в «{escape(target.name)}».\nКоличество товаров: <b>{count}</b>.",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:category:move:apply:"))
async def admin_category_move_apply(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        _, _, _, _, source_id, target_id = callback.data.split(":")
        source_id, target_id = int(source_id), int(target_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректные категории", show_alert=True)
        return
    source = await session.get(Category, source_id)
    target = await session.get(Category, target_id)
    if not source or not target or source_id == target_id:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    products = (await session.scalars(
        select(Product).where(Product.category_id == source_id)
    )).all()
    moved = len(products)
    for product in products:
        product.category_id = target_id
    await session.commit()
    await callback.message.edit_text(
        f"✅ Перенесено товаров: <b>{moved}</b>\n"
        f"Из: {escape(source.name)}\nВ: {escape(target.name)}",
        reply_markup=_category_actions_keyboard(source, 0),
    )
    await callback.answer("Товары перенесены")


@router.callback_query(F.data.startswith("admin:category:delete:"))
async def admin_category_delete(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        category_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    category = await session.get(Category, category_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    count = await session.scalar(
        select(func.count(Product.id)).where(Product.category_id == category_id)
    ) or 0
    if count:
        await callback.answer("Категория не пуста — сначала перенеси товары.", show_alert=True)
        return
    name = category.name
    await session.delete(category)
    await session.commit()
    rows = await _category_rows(session)
    await callback.message.edit_text(
        f"🗑 Категория «{escape(name)}» удалена.",
        reply_markup=_category_list_keyboard(rows),
    )
    await callback.answer("Удалено")


@router.callback_query(F.data == "admin:commands")
async def admin_commands_callback(callback: CallbackQuery):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        _admin_commands_text(),
        reply_markup=_admin_commands_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "ui:close")
async def close_message_callback(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        await callback.answer("Не удалось закрыть сообщение", show_alert=True)
        return
    await callback.answer("Закрыто")


def _admin_commands_text():
    return (
        "🛠 <b>Команды администратора</b>\n\n"
        "/admin — открыть панель администратора\n"
        "/adminhelp — список команд администратора\n"
        "/categories — управление категориями\n"
        "/addcategory НАЗВАНИЕ — создать категорию\n"
        "/deletecategory ID — удалить пустую категорию\n"
        "/addproduct CATEGORY_ID | НАЗВАНИЕ | ЦЕНА | ОПИСАНИЕ — создать товар\n"
        "/products — список товаров и ID\n"
        "/setprice PRODUCT_ID ЦЕНА — изменить розничную цену\n"
        "/setmarkup ПРОЦЕНТ — изменить наценку поставщика\n"
        "/setdescription PRODUCT_ID — изменить описание\n"
        "/addkey PRODUCT_ID | CDK — добавить CDK\n"
        "/credit USER_ID СУММА — начислить баланс\n"
        "/orders — список заказов по страницам\n"
        "/linksupplier PRODUCT_ID SUPPLIER_ID — связать товар с поставщиком\n"
        "/supplierbalance — баланс Sandromania\n"
        "/supplierproducts — информация о каталоге поставщика\n"
        "/syncsupplier — синхронизировать каталог\n"
        "/cancel — отменить текущий ввод\n"
        "/clear — очистить описание товара"
    )


def _admin_commands_keyboard():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню администратора", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("adminhelp"))
async def admin_help_command(message: Message):
    if not is_admin(message):
        return
    await message.answer(_admin_commands_text(), reply_markup=_admin_commands_keyboard())


@router.message(Command("admin"))
async def admin_help(message: Message):
    if not is_admin(message):
        return
    await message.answer(
        "<b>Панель администратора</b>\nВыбери нужный раздел:",
        reply_markup=admin_keyboard(),
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

@router.message(Command("setdescription"))
async def set_product_description(message: Message, state: FSMContext, session):
    if not is_admin(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip().isdigit():
        await message.answer("Формат: /setdescription PRODUCT_ID")
        return
    product_id = int(parts[1].strip())
    product = await session.get(Product, product_id)
    if not product:
        await message.answer("Товар не найден. Используй /products.")
        return
    await state.set_state(DescriptionStates.waiting_for_description)
    await state.update_data(description_product_id=product_id)
    await message.answer(
        f"Отправь новое описание для товара «{product.name}».\n"
        "Можно отправить несколько абзацев. Чтобы удалить описание, отправь /clear.\n"
        "Для отмены — /cancel."
    )


@router.message(DescriptionStates.waiting_for_description, Command("cancel"))
async def cancel_description_edit(message: Message, state: FSMContext):
    if not is_admin(message):
        await state.clear()
        return
    await state.clear()
    await message.answer("Редактирование описания отменено.")


@router.message(DescriptionStates.waiting_for_description, Command("clear"))
async def clear_product_description(message: Message, state: FSMContext, session):
    if not is_admin(message):
        await state.clear()
        return
    data = await state.get_data()
    product = await session.get(Product, data.get("description_product_id"))
    if not product:
        await state.clear()
        await message.answer("Товар не найден.")
        return
    product.description = ""
    await session.commit()
    await state.clear()
    await message.answer(f"Описание товара «{product.name}» очищено.")


@router.message(DescriptionStates.waiting_for_description)
async def save_product_description(message: Message, state: FSMContext, session):
    if not is_admin(message):
        await state.clear()
        return
    description = (message.text or message.caption or "").strip()
    if not description:
        await message.answer("Пришли текстовое описание сообщением.")
        return
    if len(description) > 10000:
        await message.answer("Описание слишком длинное. Максимум — 10 000 символов.")
        return
    data = await state.get_data()
    product = await session.get(Product, data.get("description_product_id"))
    if not product:
        await state.clear()
        await message.answer("Товар не найден.")
        return
    product.description = description
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Описание сохранено для товара «{product.name}».\n"
        "Оно будет показываться в карточке товара, но не на экране оплаты."
    )


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
    if not is_admin(message):
        return
    text, keyboard = await _get_detailed_orders(session, page=1, page_size=5)
    await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


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
    # Do not reactivate an intentionally hidden product when its price changes.
    active_label = "активен" if product.is_active else "выключен"
    await session.commit()
    await message.answer(
        f"Розничная цена товара «{product.name}» установлена: {price:.2f} ₽. "
        f"Статус товара не изменён: {active_label}."
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

@router.callback_query(F.data == "admin:descriptions")
async def admin_descriptions(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    rows = (await session.scalars(select(Product).order_by(Product.name).limit(50))).all()
    if not rows:
        await callback.message.edit_text("В базе пока нет товаров.", reply_markup=admin_keyboard())
        await callback.answer()
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for product in rows:
        status = "есть описание" if (product.description or "").strip() else "без описания"
        kb.button(
            text=f"{product.name[:42]} · {status}",
            callback_data=f"admin:description:edit:{product.id}",
        )
    kb.button(text="⬅️ В меню", callback_data="admin:home")
    kb.adjust(1)
    await callback.message.edit_text(
        "<b>📝 Описания товаров</b>\nВыбери товар, описание которого нужно добавить или изменить:",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:description:edit:"))
async def admin_description_edit(callback: CallbackQuery, state: FSMContext, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        product_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный товар", show_alert=True)
        return
    product = await session.get(Product, product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await state.set_state(DescriptionStates.waiting_for_description)
    await state.update_data(description_product_id=product.id)
    await callback.message.answer(
        f"📝 <b>{product.name}</b>\n"
        "Отправь новое описание следующим сообщением. Можно использовать эмодзи и переносы строк.\n"
        "Чтобы удалить описание, отправь /clear. Для отмены — /cancel."
    )
    await callback.answer()



# ---------- Управление товарами: включение, отключение и полное удаление ----------

def _product_management_keyboard(products):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for product in products:
        state = "🟢" if product.is_active else "⚫"
        kb.button(
            text=f"{state} {product.name[:38]} · #{product.id}",
            callback_data=f"admin:product:manage:{product.id}",
        )
    kb.button(text="⬅️ В меню", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def _product_actions_keyboard(product):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    if product.is_active:
        kb.button(text="⏸ Отключить из каталога", callback_data=f"admin:product:toggle:{product.id}:off")
    else:
        kb.button(text="▶️ Включить в каталог", callback_data=f"admin:product:toggle:{product.id}:on")
    kb.button(text="🗑 Удалить товар полностью", callback_data=f"admin:product:delete:confirm:{product.id}")
    kb.button(text="⬅️ К списку товаров", callback_data="admin:products")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "admin:products")
async def admin_products_list(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    products = (await session.scalars(select(Product).order_by(Product.name).limit(100))).all()
    if not products:
        await callback.message.edit_text("В базе пока нет товаров.", reply_markup=admin_keyboard())
    else:
        await callback.message.edit_text(
            "<b>📦 Управление товарами</b>\n\n"
            "🟢 — отображается в каталоге\n"
            "⚫ — отключён\n\nВыбери товар:",
            reply_markup=_product_management_keyboard(products),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:product:manage:"))
async def admin_product_manage(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        product_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    product = await session.get(Product, product_id)
    if not product:
        await callback.answer("Товар уже удалён или не найден", show_alert=True)
        return
    local_keys = await session.scalar(
        select(func.count(DigitalKey.id)).where(DigitalKey.product_id == product_id)
    )
    orders_count = await session.scalar(
        select(func.count(Order.id)).where(Order.product_id == product_id)
    )
    await callback.message.edit_text(
        f"<b>📦 {product.name}</b>\n"
        f"ID: <code>{product.id}</code>\n"
        f"Цена: {product.price:.2f} ₽\n"
        f"Статус: {'🟢 Активен' if product.is_active else '⚫ Отключён'}\n"
        f"CDK-записей: {local_keys}\n"
        f"Заказов: {orders_count}\n\n"
        "Выбери действие:",
        reply_markup=_product_actions_keyboard(product),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:product:toggle:"))
async def admin_product_toggle(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")
    try:
        product_id = int(parts[3])
        turn_on = parts[4] == "on"
    except (ValueError, IndexError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    product = await session.get(Product, product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    product.is_active = turn_on
    await session.commit()
    # Refresh before showing updated state.
    await session.refresh(product)
    await callback.message.edit_text(
        f"<b>📦 {product.name}</b>\n"
        f"Статус изменён: {'🟢 Активен в каталоге' if turn_on else '⚫ Отключён от каталога'}.\n\n"
        "Изменение сохранено в базе данных.",
        reply_markup=_product_actions_keyboard(product),
    )
    await callback.answer("Товар включён" if turn_on else "Товар отключён")


@router.callback_query(F.data.startswith("admin:product:delete:confirm:"))
async def admin_product_delete_confirm(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        product_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    product = await session.get(Product, product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    orders_count = await session.scalar(
        select(func.count(Order.id)).where(Order.product_id == product_id)
    )
    keys_count = await session.scalar(
        select(func.count(DigitalKey.id)).where(DigitalKey.product_id == product_id)
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="⚠️ Да, удалить полностью", callback_data=f"admin:product:delete:do:{product_id}")
    kb.button(text="Отмена", callback_data=f"admin:product:manage:{product_id}")
    kb.adjust(1)
    await callback.message.edit_text(
        f"⚠️ <b>Полное удаление товара</b>\n\n"
        f"Товар: <b>{product.name}</b> (ID {product.id})\n"
        f"Будут удалены CDK-записи: <b>{keys_count}</b>\n"
        f"Будут удалены заказы: <b>{orders_count}</b>\n"
        "Также будут удалены связанные платежи этих заказов.\n\n"
        "<b>Это действие необратимо.</b> Покупки исчезнут из истории заказов пользователей. "
        "Записи бухгалтерских транзакций пользователей сохраняются отдельно.",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:product:delete:do:"))
async def admin_product_delete_do(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        product_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректный ID", show_alert=True)
        return
    product = await session.get(Product, product_id)
    if not product:
        await callback.answer("Товар уже удалён", show_alert=True)
        return

    in_flight = await session.scalar(
        select(func.count(Order.id)).where(
            Order.product_id == product_id,
            Order.status.in_(["PENDING", "PAID", "PROCESSING"]),
        )
    )
    if in_flight:
        await callback.answer(
            f"Нельзя удалить: у товара {in_flight} незавершённых заказов. "
            "Сначала разберись с ними.",
            show_alert=True,
        )
        return

    # Remove dependent rows in FK-safe order. Keep generic user ledger transactions.
    order_ids = select(Order.id).where(Order.product_id == product_id)
    await session.execute(delete(Payment).where(Payment.order_id.in_(order_ids)))
    await session.execute(delete(DigitalKey).where(DigitalKey.product_id == product_id))
    await session.execute(delete(Order).where(Order.product_id == product_id))
    product_name = product.name
    await session.delete(product)
    await session.commit()

    await callback.message.edit_text(
        f"🗑 Товар <b>{product_name}</b> (ID {product_id}) полностью удалён.\n"
        "Связанные CDK, заказы и платежи удалены. "
        "Общие записи балансовых транзакций сохранены.",
        reply_markup=admin_keyboard(),
    )
    await callback.answer("Товар удалён")

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
    text, keyboard = await _get_detailed_orders(session, page=1, page_size=5)
    await callback.message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:orders:page:"))
async def admin_orders_page_callback(callback: CallbackQuery, session):
    if not _is_admin_callback(callback):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        page = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная страница", show_alert=True)
        return
    text, keyboard = await _get_detailed_orders(session, page=page, page_size=5)
    try:
        await callback.message.edit_text(
            text, reply_markup=keyboard, disable_web_page_preview=True
        )
    except Exception:
        await callback.message.answer(
            text, reply_markup=keyboard, disable_web_page_preview=True
        )
    await callback.answer()


@router.callback_query(F.data == "admin:orders:current")
async def admin_orders_current_callback(callback: CallbackQuery):
    await callback.answer("Текущая страница заказов")
