from pathlib import Path
from aiogram.types import FSInputFile, InputMediaPhoto, Message
from aiogram.exceptions import TelegramBadRequest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BANNER_DIR = PROJECT_ROOT / "assets" / "banners"

# One active screen per private chat. The screen is also edited on callback navigation.
_ACTIVE_SCREENS: dict[int, int] = {}

def product_banner(product) -> str:
    name = str(getattr(product, "name", "")).casefold()
    rules = (
        (("claude",), "claude.png"),
        (("gemini",), "gemini.png"),
        (("capcut", "cap cut"), "capcut.png"),
        (("chatgpt", "chat gpt", "чат гпт"), "chatgpt.png"),
        (("adobe", "photoshop", "premiere", "acrobat"), "adobe.png"),
    )
    for needles, filename in rules:
        if any(word in name for word in needles):
            return filename
    return "catalog.png"

async def _delete_previous(bot, chat_id: int, keep_message_id: int | None = None):
    previous_id = _ACTIVE_SCREENS.get(chat_id)
    if previous_id and previous_id != keep_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=previous_id)
        except TelegramBadRequest:
            pass
    if keep_message_id is not None:
        _ACTIVE_SCREENS[chat_id] = keep_message_id
    else:
        _ACTIVE_SCREENS.pop(chat_id, None)

async def send_section(target: Message, banner_name: str, caption: str, reply_markup=None):
    chat_id = target.chat.id
    bot = target.bot
    path = BANNER_DIR / banner_name

    # User message: it is a slash command or text navigation. Remove it and replace
    # the previously displayed screen instead of stacking another message.
    if target.from_user and not target.from_user.is_bot:
        try:
            await target.delete()
        except TelegramBadRequest:
            pass
        await _delete_previous(bot, chat_id)
        if path.is_file():
            sent = await bot.send_photo(
                chat_id=chat_id, photo=FSInputFile(path),
                caption=caption, reply_markup=reply_markup,
            )
        else:
            sent = await bot.send_message(
                chat_id=chat_id, text=caption, reply_markup=reply_markup,
            )
        _ACTIVE_SCREENS[chat_id] = sent.message_id
        return sent

    # Callback from a bot screen: remove any older tracked screen, then edit
    # the message containing the pressed button in place.
    await _delete_previous(bot, chat_id, keep_message_id=target.message_id)
    try:
        if target.photo and path.is_file():
            media = InputMediaPhoto(media=FSInputFile(path), caption=caption)
            edited = await bot.edit_message_media(
                chat_id=chat_id, message_id=target.message_id,
                media=media, reply_markup=reply_markup,
            )
        elif target.photo:
            edited = await bot.edit_message_caption(
                chat_id=chat_id, message_id=target.message_id,
                caption=caption, reply_markup=reply_markup,
            )
        elif path.is_file():
            edited = await bot.edit_message_media(
                chat_id=chat_id, message_id=target.message_id,
                media=InputMediaPhoto(media=FSInputFile(path), caption=caption),
                reply_markup=reply_markup,
            )
        else:
            edited = await bot.edit_message_text(
                chat_id=chat_id, message_id=target.message_id,
                text=caption, reply_markup=reply_markup,
            )
        _ACTIVE_SCREENS[chat_id] = target.message_id
        return edited
    except TelegramBadRequest as exc:
        # For example: a legacy message may be too old or not editable as expected.
        await _delete_previous(bot, chat_id, keep_message_id=target.message_id)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=target.message_id)
        except TelegramBadRequest:
            pass
        if path.is_file():
            sent = await bot.send_photo(chat_id=chat_id, photo=FSInputFile(path),
                                        caption=caption, reply_markup=reply_markup)
        else:
            sent = await bot.send_message(chat_id=chat_id, text=caption,
                                          reply_markup=reply_markup)
        _ACTIVE_SCREENS[chat_id] = sent.message_id
        return sent
