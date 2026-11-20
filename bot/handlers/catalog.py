from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select
from database.models.category import Category
from database.models.product import Product
from bot.keyboards.catalog import categories_keyboard
from bot.keyboards.products import products_keyboard
from bot.utils.section_media import send_section, product_banner

router = Router()

async def _get_categories(session):
    return (await session.scalars(
        select(Category)
        .join(Product, Product.category_id == Category.id)
        .where(Category.is_active.is_(True), Product.is_active.is_(True), Product.price > 0)
        .distinct().order_by(Category.name)
    )).all()

async def _show_catalog(target, session, edit=False):
    categories = await _get_categories(session)
    if categories:
        text = (
            "🛍 <b>BDAKA SHOP · КАТАЛОГ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Выберите интересующий раздел.\n"
            "Актуальное наличие отображается в карточках товаров."
        )
    else:
        text = "🛍 <b>BDAKA SHOP · КАТАЛОГ</b>\n\nПока нет опубликованных товаров."
    # Фото-сообщение нельзя заменить через edit_text, поэтому отправляем новый экран.
    await send_section(target, "catalog.png", text, reply_markup=categories_keyboard(categories))

@router.message(Command("catalog"))
@router.message(F.text.in_({"🛍 Каталог", "📦 Каталог"}))
async def catalog(message: Message, session):
    await _show_catalog(message, session)

@router.callback_query(F.data == "menu:catalog")
async def catalog_from_home(callback: CallbackQuery, session):
    await _show_catalog(callback.message, session)
    await callback.answer()

@router.callback_query(F.data == "back:catalog")
async def back_to_catalog(callback: CallbackQuery, session):
    await _show_catalog(callback.message, session)
    await callback.answer()

@router.callback_query(F.data == "refresh:catalog")
async def refresh_catalog(callback: CallbackQuery, session):
    await _show_catalog(callback.message, session)
    await callback.answer("Каталог обновлён")

@router.callback_query(F.data.startswith("cat:"))
async def category_products(callback: CallbackQuery, session):
    try:
        category_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная категория", show_alert=True)
        return
    category = await session.get(Category, category_id)
    if not category or not category.is_active:
        await callback.answer("Раздел недоступен", show_alert=True)
        return
    products = (await session.scalars(
        select(Product).where(
            Product.category_id == category_id,
            Product.is_active.is_(True),
            Product.price > 0,
        ).order_by(Product.name)
    )).all()
    if not products:
        await callback.answer("В этом разделе пока нет товаров", show_alert=True)
        return
    text = (
        f"📁 <b>{category.name}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Выберите товар. Остаток указан по последним данным поставщика."
    )
    await send_section(callback.message, product_banner(products[0]), text,
                       reply_markup=products_keyboard(products))
    await callback.answer()

@router.callback_query(F.data == "back:products")
async def back_to_products(callback: CallbackQuery, session):
    await _show_catalog(callback.message, session)
    await callback.answer()

@router.callback_query(F.data == "stock:unavailable")
async def unavailable_info(callback: CallbackQuery):
    await callback.answer("Товар временно отсутствует. Покупка недоступна.", show_alert=True)
