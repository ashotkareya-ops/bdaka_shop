from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import hashlib
import secrets
import logging
from utils.partner_crypto import encrypt_partner_secret
from datetime import datetime
from sqlalchemy import text
from sqlalchemy import select
from database.models.user import User
from config.settings import settings
from bot.keyboards.profile import profile_keyboard
from bot.utils.section_media import send_section

router = Router()
log = logging.getLogger(__name__)

PRIVACY_TEXT = r"""🔐 <b>ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ BDAKA SHOP</b>
Редакция от 24 ноября 2026 года

<b>1. Общие положения</b>
Настоящая Политика описывает, какие данные обрабатываются при использовании Telegram-бота BDAKA SHOP (далее — Магазин), для каких целей и как они защищаются. Используя бота и оформляя заказ, пользователь подтверждает, что ознакомился с Политикой.

<b>2. Какие данные обрабатываются</b>
Магазин может обрабатывать:
• Telegram ID пользователя;
• имя и username в Telegram, если они доступны;
• сведения о заказах, покупках, обращениях в поддержку и начислениях на внутренний баланс;
• сведения о платежах и статусах оплаты, полученные от платёжных сервисов;
• адрес электронной почты, если он предоставлен пользователем или требуется для конкретного способа оплаты или товара;
• технические сведения, необходимые для защиты бота и предотвращения злоупотреблений.

Магазин не запрашивает данные банковских карт и не хранит их полные реквизиты. Платёжные данные обрабатываются соответствующим платёжным провайдером.

<b>3. Цели обработки</b>
Данные используются для регистрации и идентификации пользователя в боте, оформления и исполнения заказов, приёма и проверки платежей, выдачи цифровых товаров, ведения истории операций, ответа на обращения, предотвращения мошенничества, обеспечения безопасности и выполнения требований законодательства.

<b>4. Передача данных третьим лицам</b>
Для исполнения заказа необходимые сведения могут передаваться платёжным провайдерам (в том числе Platega, если этот способ оплаты используется), поставщикам цифровых товаров и техническим сервисам, обеспечивающим работу Магазина. Данные также могут быть предоставлены государственным органам в случаях и порядке, предусмотренных законодательством. Магазин не продаёт персональные данные пользователей.

<b>5. Хранение и защита</b>
Данные хранятся столько, сколько необходимо для указанных целей, исполнения обязательств и соблюдения установленных законом сроков. Магазин принимает разумные организационные и технические меры для защиты данных от неправомерного доступа, изменения, раскрытия или уничтожения.

<b>6. Права пользователя и обращения</b>
Пользователь может обратиться за уточнением сведений, сообщить об ошибке или запросить прекращение обработки данных, если для их дальнейшего хранения и обработки нет законного основания. Для обращения напишите в поддержку: @bdaka1 — https://t.me/bdaka1.

<b>7. Изменение Политики</b>
Магазин вправе обновлять Политику. Актуальная редакция доступна в разделе «Профиль» Telegram-бота BDAKA SHOP. Продолжение использования бота после публикации изменений означает ознакомление пользователя с обновлённой редакцией.

<b>8. Контакты</b>
По вопросам обработки данных и работы Магазина: https://t.me/bdaka1
"""

AGREEMENT_TEXT = r"""📄 <b>ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ BDAKA SHOP</b>
Редакция от 24 ноября 2026 года

<b>1. Общие положения</b>
Настоящее Соглашение регулирует использование Telegram-бота BDAKA SHOP (далее — Магазин) и порядок оформления заказов на цифровые товары. Используя бота, пользователь подтверждает, что ознакомился с условиями Соглашения.

<b>2. Товары и информация о них</b>
Магазин предлагает цифровые товары: коды активации, лицензии, подписки, доступы, приглашения и сопутствующие цифровые продукты. Состав, срок действия, ограничения, способ получения и стоимость указываются в карточке соответствующего товара. Пользователь должен ознакомиться с описанием до оплаты.

<b>3. Оформление и оплата заказа</b>
Заказ оформляется через интерфейс бота. Стоимость заказа отображается до подтверждения оплаты. Оплата производится доступными в боте способами, в том числе через подключённого платёжного провайдера (например, Platega, если он доступен). Заказ считается оплаченным после получения Магазином подтверждения от платёжной системы.

<b>4. Выдача цифрового товара</b>
После подтверждения оплаты товар выдаётся автоматически либо способом, указанным в карточке товара. В зависимости от продукта это может быть код, ссылка-приглашение, данные доступа или инструкция. Пользователь обязан самостоятельно проверить корректность введённых данных и соблюдать условия использования приобретённого продукта.

<b>5. Обязанности пользователя</b>
Пользователь обязуется предоставлять корректные сведения, не использовать Магазин для противоправных действий, не пытаться вмешиваться в работу бота и не передавать третьим лицам полученные данные доступа, если это запрещено условиями конкретного товара.

<b>6. Проблемы с заказом, возвраты и замены</b>
Если товар не получен, код не работает или возникла другая проблема, пользователь должен обратиться в поддержку и указать номер заказа и описание проблемы. Магазин проверит обращение и при подтверждении недостатка предложит предусмотренное законом решение, включая исправление, замену или возврат денежных средств, если это применимо. Условия возврата определяются законодательством Российской Федерации. Сам по себе цифровой формат товара не отменяет права потребителя, предусмотренные законом.

<b>7. Ограничение ответственности</b>
Магазин не отвечает за невозможность использования товара вследствие нарушения пользователем инструкции, передачи данных доступа третьим лицам, изменения условий стороннего сервиса или иных обстоятельств вне контроля Магазина. Это положение не ограничивает права пользователя, которые не могут быть ограничены законом.

<b>8. Поддержка</b>
По вопросам оплаты, получения товара, качества и возврата обратитесь в поддержку: @bdaka1 — https://t.me/bdaka1.

<b>9. Изменение Соглашения</b>
Магазин может обновлять Соглашение. Актуальная редакция доступна в разделе «Профиль» Telegram-бота BDAKA SHOP. Новая редакция применяется с момента её публикации, если иное не указано в тексте изменений.

<b>10. Контакты</b>
Поддержка BDAKA SHOP: https://t.me/bdaka1
"""


async def _send_profile(target, user):
    text = (
        "👤 <b>ПРОФИЛЬ</b>\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"💰 Баланс: <b>{user.balance:.2f} ₽</b>\n"
        f"🛍 Покупок: <b>{user.purchase_count}</b>\n\n"
        "Выберите нужный раздел:"
    )
    await send_section(target, "profile.png", text, reply_markup=profile_keyboard())


def _document_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ Назад в профиль", callback_data="profile:home")
    kb.adjust(1)
    return kb.as_markup()


async def _show_document(callback: CallbackQuery, text: str):
    # Acknowledge the button immediately so Telegram does not keep the
    # loading spinner while the document message is being sent.
    await callback.answer()

    try:
        await callback.message.delete()
    except Exception:
        pass

    # Send as a normal message, not a photo caption: Telegram captions have
    # a 1024-character limit, while text messages support up to 4096 chars.
    await callback.bot.send_message(
        chat_id=callback.message.chat.id,
        text=text,
        reply_markup=_document_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def profile(message: Message, session):
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    await _send_profile(message, user)


@router.callback_query(F.data == "menu:profile")
async def profile_from_home(callback: CallbackQuery, session):
    await callback.answer()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if not user:
        await callback.message.answer("Сначала нажмите /start")
        return
    await _send_profile(callback.message, user)


@router.callback_query(F.data == "profile:privacy")
async def profile_privacy(callback: CallbackQuery):
    await _show_document(callback, PRIVACY_TEXT)


@router.callback_query(F.data == "profile:agreement")
async def profile_agreement(callback: CallbackQuery):
    await _show_document(callback, AGREEMENT_TEXT)


@router.callback_query(F.data == "profile:home")
async def profile_home(callback: CallbackQuery, session):
    await callback.answer()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if not user:
        await callback.message.answer("Пользователь не найден")
        return
    await _send_profile(callback.message, user)


# ---------------------------------------------------------------------------
# Partner API access. Secret Key is shown once; only encrypted at rest.
# ---------------------------------------------------------------------------

def _partner_api_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 Документация API", callback_data="partner:docs")
    kb.button(text="🔑 Получить API-ключи", callback_data="partner:keys")
    kb.button(text="↩️ Назад в профиль", callback_data="profile:home")
    kb.adjust(1)
    return kb.as_markup()


def _partner_keys_keyboard(has_active_key: bool = False):
    kb = InlineKeyboardBuilder()
    if has_active_key:
        kb.button(text="🔄 Перевыпустить пару ключей", callback_data="partner:rotate")
    else:
        kb.button(text="🔑 Создать пару ключей", callback_data="partner:create")
    kb.button(text="↩️ Назад", callback_data="partner:api")
    kb.adjust(1)
    return kb.as_markup()



@router.callback_query(F.data == "partner:api")
async def partner_api_info(callback: CallbackQuery):
    await callback.answer()

    api_url = settings.api_public_url.rstrip("/") if settings.api_public_url else None

    text = (
        "🤝 <b>ПАРТНЁРСКИЙ API BDAKA STORE</b>\n\n"
        "Подключите свой сайт или Telegram-бот к BDAKA STORE "
        "и автоматизируйте получение товаров и оформление заказов.\n\n"
        "🔹 Просмотр каталога и цен\n"
        "🔹 Проверка баланса\n"
        "🔹 Создание заказов\n"
        "🔹 Получение статусов и цифровой выдачи\n\n"
        "💰 <b>Единый баланс</b>\n"
        "Заказы через API оплачиваются с вашего обычного баланса BDAKA SHOP. "
        "Отдельное пополнение не требуется.\n\n"
        "🔐 <b>Подключение</b>\n"
        "Каждому партнёру выдаются индивидуальные Public Key и Secret Key. "
        "Настройте их один раз — подпись запросов будет формироваться автоматически.\n\n"
    )

    if api_url:
        text += f"🌐 <b>Адрес API:</b>\n<code>{api_url}</code>\n\n"

    text += "Выберите нужный раздел:"

    await callback.message.answer(
        text,
        reply_markup=_partner_api_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "partner:keys")
async def partner_api_keys_menu(callback: CallbackQuery, session):
    await callback.answer()
    user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
    if not user:
        await callback.message.answer("Сначала нажмите /start")
        return
    result = await session.execute(text("""
        SELECT p.id AS partner_id, k.key_prefix
        FROM partners p
        LEFT JOIN partner_api_keys k ON k.partner_id = p.id AND k.is_active = TRUE
        WHERE p.user_id = :user_id
        ORDER BY k.id DESC LIMIT 1
    """), {"user_id": user.id})
    partner = result.mappings().first()
    has_key = bool(partner and partner.get("key_prefix"))
    body = (
        "🔐 <b>УПРАВЛЕНИЕ API-КЛЮЧАМИ</b>\n\n"
        + (f"Активная пара найдена. Префикс Public Key: <code>{partner['key_prefix']}</code>.\n"
           "Secret Key повторно не показывается. Если он утерян или раскрыт, перевыпустите пару.\n\n"
           if has_key else "У вас пока нет активной пары ключей.\n\n")
        + "При перевыпуске предыдущая пара немедленно отключается. Сохраните новую пару в защищённом месте."
    )
    await callback.message.answer(body, reply_markup=_partner_keys_keyboard(has_key))


@router.callback_query(F.data == "partner:docs")
async def partner_api_docs(callback: CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text="↩️ Назад", callback_data="partner:api")
    kb.adjust(1)
    docs = (
        "📚 <b>ДОКУМЕНТАЦИЯ BDAKA STORE API</b>\n\n"
        "<b>Авторизация</b>\n"
        "Каждый запрос подписывается HMAC-SHA256. Партнёр получает пару ключей в этом боте.\n"
        + (f"Базовый адрес: <code>{settings.api_public_url.rstrip('/')}</code>\n\n" if settings.api_public_url else "Базовый HTTPS-адрес API уточните у поддержки.\n\n")
        + "Используется ваш обычный баланс BDAKA SHOP: пополнение и списание общие для покупок в боте и через API.\n"
        "• Public Key отправляется в заголовке <code>X-API-Key</code>.\n"
        "• Secret Key используется только локально для подписи и никогда не отправляется серверу.\n\n"
        "<b>Обязательные заголовки</b>\n"
        "<code>X-API-Key</code> — Public Key\n"
        "<code>X-Timestamp</code> — Unix-время в секундах\n"
        "<code>X-Nonce</code> — случайная уникальная строка (16–128 символов)\n"
        "<code>X-Signature</code> — hex HMAC-SHA256\n\n"
        "<b>Строка для подписи</b>\n"
        "<code>METHOD\nPATH_AND_QUERY\nTIMESTAMP\nNONCE\nSHA256_HEX(BODY)</code>\n"
        "HMAC вычисляется алгоритмом SHA-256 с Secret Key в качестве ключа. Для GET без тела используется пустое тело. "
        "Подписывайте точные путь, query string и байты JSON, которые отправляете. Время допускается с отклонением до 5 минут; повторный Nonce отклоняется.\n\n"
        "<b>Доступные методы</b>\n"
        "<code>GET /api/v1/partners/me</code> — профиль партнёра\n"
        "<code>GET /api/v1/products</code> — каталог\n"
        "<code>GET /api/v1/products/{id}</code> — товар\n"
        "<code>GET /api/v1/categories</code> — категории\n"
        "<code>GET /api/v1/balance</code> — баланс\n"
        "<code>GET /api/v1/balance/transactions</code> — операции\n"
        "<code>POST /api/v1/orders</code> — создать заказ\n"
        "<code>GET /api/v1/orders</code> — список заказов\n"
        "<code>GET /api/v1/orders/{id}</code> — статус и выдача\n\n"
        "<b>Создание заказа</b>\n"
        "JSON: <code>{\"product_id\": 8, \"quantity\": 1}</code>. Обязательно передавайте уникальный <code>Idempotency-Key</code> (16–120 символов). Повтор одного запроса должен использовать тот же ключ. Заказ реальный: средства списываются, после чего бот выполняет выдачу.\n\n"
        "<b>Безопасность</b>\n"
        "Не вставляйте Secret Key в публичный код, frontend, Git или сообщения. Храните его в переменных окружения на сервере. При утечке немедленно перевыпустите пару. Используйте HTTPS в production.\n\n"
        "После POST /orders проверяйте GET /orders/{id}, пока статус не станет COMPLETED; только тогда передавайте delivery своему клиенту.\n"
        "Примеры Python, Node.js и PHP и подробная документация выдаются вместе с партнёрским SDK. Не отправляйте Secret Key в браузер."
    )
    await callback.message.answer(docs, reply_markup=kb.as_markup())


async def _issue_partner_token(session, telegram_user, rotate: bool) -> str:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_user.id).with_for_update())
    if not user:
        raise ValueError("Пользователь не найден")

    partner_result = await session.execute(text("""
        INSERT INTO partners (user_id, name, is_active, created_at)
        VALUES (:user_id, :name, TRUE, :created_at)
        ON CONFLICT (user_id)
        DO UPDATE SET name = EXCLUDED.name, is_active = TRUE
        RETURNING id
    """), {
        "user_id": user.id,
        "name": (telegram_user.full_name or telegram_user.username or f"Partner {telegram_user.id}")[:120],
        "created_at": datetime.utcnow(),
    })
    partner_id = int(partner_result.scalar_one())

    active_result = await session.execute(text("""
        SELECT id FROM partner_api_keys
        WHERE partner_id = :partner_id AND is_active = TRUE
        ORDER BY id DESC LIMIT 1
        FOR UPDATE
    """), {"partner_id": partner_id})
    active_key = active_result.scalar_one_or_none()
    if active_key is not None and not rotate:
        raise ValueError("У вас уже есть активная пара ключей. Выберите перевыпуск, если Secret Key потерян.")

    now = datetime.utcnow()
    if rotate:
        await session.execute(text("""
            UPDATE partner_api_keys
            SET is_active = FALSE, revoked_at = :now
            WHERE partner_id = :partner_id AND is_active = TRUE
        """), {"now": now, "partner_id": partner_id})

    public_key = "bdaka_pub_" + secrets.token_urlsafe(24)
    secret_key = "bdaka_sec_" + secrets.token_urlsafe(48)
    secret_encrypted = encrypt_partner_secret(secret_key)
    await session.execute(text("""
        INSERT INTO partner_api_keys
            (partner_id, token_hash, key_prefix, label, is_active, created_at, public_key, secret_encrypted)
        VALUES
            (:partner_id, :token_hash, :key_prefix, :label, TRUE, :created_at, :public_key, :secret_encrypted)
    """), {
        "partner_id": partner_id,
        "token_hash": hashlib.sha256(public_key.encode("utf-8")).hexdigest(),
        "key_prefix": public_key[:16],
        "label": "Telegram bot",
        "created_at": now,
        "public_key": public_key,
        "secret_encrypted": secret_encrypted,
    })
    await session.commit()
    return public_key + "\n" + secret_key


@router.callback_query(F.data.in_({"partner:create", "partner:rotate"}))
async def partner_api_issue_token(callback: CallbackQuery, session):
    rotate = callback.data == "partner:rotate"
    await callback.answer()
    try:
        token = await _issue_partner_token(session, callback.from_user, rotate)
    except ValueError as exc:
        await session.rollback()
        await callback.message.answer(str(exc))
        return
    except Exception:
        await session.rollback()
        log.exception("Could not issue partner API token for telegram_id=%s", callback.from_user.id)
        await callback.message.answer("Не удалось выпустить ключи. Проверьте настройки шифрования и попробуйте позже.")
        return

    await callback.message.answer(
        "🔐 <b>Ваша новая пара API-ключей</b>\n\n"
        f"<b>Public Key</b> (идентификатор):\n<code>{token.splitlines()[0]}</code>\n\n"
        f"<b>Secret Key</b> (секрет подписи):\n<code>{token.splitlines()[1]}</code>\n\n"
        "<b>Сохраните оба ключа сейчас.</b> Secret Key повторно показать нельзя. "
        "При перевыпуске предыдущая пара перестаёт работать.\n\n"
        "Public Key передаётся в <code>X-API-Key</code>, Secret Key используется только для HMAC-SHA256 подписи. Никому не отправляйте Secret Key."
    )
