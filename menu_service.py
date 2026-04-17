"""
Сервис динамического меню: клавиатуры, сохранение контента и отправка узлов.
"""
import json
import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    KeyboardButton,
    Message,
    MessageEntity,
    PhotoSize,
    ReplyKeyboardMarkup,
)

from database import (
    add_early_access_user,
    find_menu_child_by_title,
    get_main_greeting,
    get_menu_media,
    get_menu_node,
    get_user_reply_menu_message,
    get_user_reply_message_ids,
    get_user_reply_menu_parent,
    list_menu_children,
    set_user_reply_menu_message,
    set_user_reply_message_ids,
    set_user_reply_menu_parent,
)

logger = logging.getLogger(__name__)

MENU_CALLBACK_PREFIX = "menu:"
MENU_BACK_PREFIX = "menu_back:"
LOST_ITEM_TEXT = "Я забыл свои вещи в К-30"
REPLY_BACK_TEXT = "← Назад"

def _button_kwargs(style: str | None) -> dict[str, str]:
    return {"style": style} if style else {}


def _dynamic_button(node: dict[str, Any]) -> InlineKeyboardButton:
    kwargs = _button_kwargs(node.get("style"))
    if node["kind"] == "url":
        return InlineKeyboardButton(text=node["title"], url=node["url"], **kwargs)
    return InlineKeyboardButton(text=node["title"], callback_data=f"{MENU_CALLBACK_PREFIX}{node['id']}", **kwargs)


def build_menu_keyboard(
    parent_id: int | None,
    include_lost_item: bool = False,
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for node in list_menu_children(parent_id):
        rows.append([_dynamic_button(node)])

    if include_lost_item:
        rows.append([InlineKeyboardButton(text=LOST_ITEM_TEXT, callback_data="lost_item")])

    if include_back:
        parent = get_menu_node(parent_id) if parent_id is not None else None
        back_target = parent["parent_id"] if parent and parent["parent_id"] is not None else "root"
        rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"{MENU_BACK_PREFIX}{back_target}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_root_keyboard() -> InlineKeyboardMarkup:
    return build_menu_keyboard(parent_id=None, include_lost_item=True)


def _dynamic_reply_button(node: dict[str, Any]) -> KeyboardButton:
    kwargs = _button_kwargs(node.get("style"))
    return KeyboardButton(text=node["title"], **kwargs)


def build_reply_menu_keyboard(parent_id: int | None) -> ReplyKeyboardMarkup | None:
    rows: list[list[KeyboardButton]] = []
    for node in list_menu_children(parent_id, menu_type="reply"):
        rows.append([_dynamic_reply_button(node)])

    if parent_id is not None:
        rows.append([KeyboardButton(text=REPLY_BACK_TEXT)])

    if not rows:
        return None
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def send_reply_menu_if_any(target: Message, user_id: int | None = None):
    keyboard = build_reply_menu_keyboard(None)
    if keyboard:
        sent = await target.answer("Меню:", reply_markup=keyboard)
        owner_id = user_id if user_id is not None else (target.from_user.id if target.from_user else None)
        if owner_id:
            set_user_reply_menu_parent(owner_id, None)
            set_user_reply_menu_message(owner_id, sent.message_id)
            set_user_reply_message_ids(owner_id, [])


async def delete_processed_reply_message(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


async def delete_stored_reply_messages(message: Message):
    if not message.from_user:
        return
    message_ids = []
    menu_message_id = get_user_reply_menu_message(message.from_user.id)
    if menu_message_id:
        message_ids.append(menu_message_id)
    message_ids.extend(get_user_reply_message_ids(message.from_user.id))

    seen_ids = set()
    for message_id in message_ids:
        if message_id in seen_ids or message_id == message.message_id:
            continue
        seen_ids.add(message_id)
        try:
            await message.bot.delete_message(message.chat.id, message_id)
        except Exception:
            pass

    set_user_reply_menu_message(message.from_user.id, None)
    set_user_reply_message_ids(message.from_user.id, [])


def _entities_to_json(entities: list[MessageEntity] | None) -> str | None:
    if not entities:
        return None
    return json.dumps([entity.model_dump(mode="json") for entity in entities], ensure_ascii=False)


def entities_from_json(raw: str | None) -> list[MessageEntity] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Could not decode message entities JSON")
        return None
    return [MessageEntity.model_validate(item) for item in data]


def _largest_photo_file_id(photo: list[PhotoSize] | None) -> str | None:
    if not photo:
        return None
    return photo[-1].file_id


def extract_single_message_content(message: Message) -> dict[str, Any] | None:
    if message.text:
        return {
            "content_type": "text",
            "text": message.text,
            "entities_json": _entities_to_json(message.entities),
            "caption": None,
            "caption_entities_json": None,
            "media_file_id": None,
            "has_spoiler": False,
            "show_caption_above_media": False,
        }

    media_type = None
    file_id = None
    media_obj = None
    if message.photo:
        media_type = "photo"
        file_id = _largest_photo_file_id(message.photo)
        media_obj = message
    elif message.video:
        media_type = "video"
        media_obj = message.video
        file_id = message.video.file_id
    elif message.animation:
        media_type = "animation"
        media_obj = message.animation
        file_id = message.animation.file_id
    elif message.document:
        media_type = "document"
        media_obj = message.document
        file_id = message.document.file_id
    elif message.audio:
        media_type = "audio"
        media_obj = message.audio
        file_id = message.audio.file_id
    elif message.voice:
        media_type = "voice"
        media_obj = message.voice
        file_id = message.voice.file_id
    elif message.sticker:
        media_type = "sticker"
        media_obj = message.sticker
        file_id = message.sticker.file_id
    elif message.video_note:
        media_type = "video_note"
        media_obj = message.video_note
        file_id = message.video_note.file_id

    if media_type and file_id:
        return {
            "content_type": media_type,
            "text": None,
            "entities_json": None,
            "caption": message.caption,
            "caption_entities_json": _entities_to_json(message.caption_entities),
            "media_file_id": file_id,
            "has_spoiler": bool(getattr(media_obj, "has_spoiler", False)),
            "show_caption_above_media": bool(getattr(message, "show_caption_above_media", False)),
        }

    return None


def extract_album_content(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for position, message in enumerate(sorted(messages, key=lambda item: item.message_id)):
        media_type = None
        file_id = None
        media_obj = None
        if message.photo:
            media_type = "photo"
            file_id = _largest_photo_file_id(message.photo)
            media_obj = message
        elif message.video:
            media_type = "video"
            media_obj = message.video
            file_id = message.video.file_id
        elif message.document:
            media_type = "document"
            media_obj = message.document
            file_id = message.document.file_id
        elif message.audio:
            media_type = "audio"
            media_obj = message.audio
            file_id = message.audio.file_id

        if not media_type or not file_id:
            continue

        items.append({
            "position": position,
            "media_type": media_type,
            "file_id": file_id,
            "caption": message.caption,
            "caption_entities_json": _entities_to_json(message.caption_entities),
            "has_spoiler": bool(getattr(media_obj, "has_spoiler", False)),
            "show_caption_above_media": bool(getattr(message, "show_caption_above_media", False)),
        })
    return items


async def send_root_menu(target: Message):
    await target.answer(get_main_greeting(), reply_markup=build_root_keyboard())


async def safe_callback_answer(callback: CallbackQuery, *args, **kwargs):
    try:
        await callback.answer(*args, **kwargs)
    except TelegramBadRequest as e:
        if "query is too old" in str(e).lower() or "query id is invalid" in str(e).lower():
            logger.warning("Skipped expired callback answer: %s", e)
            return
        raise


async def replace_with_root_menu(callback: CallbackQuery):
    await safe_callback_answer(callback)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(get_main_greeting(), reply_markup=build_root_keyboard())


def _album_media_item(item: dict[str, Any]):
    common = {
        "media": item["file_id"],
        "caption": item.get("caption"),
        "caption_entities": entities_from_json(item.get("caption_entities_json")),
        "has_spoiler": bool(item.get("has_spoiler")),
        "show_caption_above_media": bool(item.get("show_caption_above_media")),
    }
    media_type = item["media_type"]
    if media_type == "photo":
        return InputMediaPhoto(**common)
    if media_type == "video":
        return InputMediaVideo(**common)
    if media_type == "document":
        return InputMediaDocument(**common)
    if media_type == "audio":
        return InputMediaAudio(**common)
    return None


async def _send_node_content(bot: Bot, chat_id: int, node: dict[str, Any], reply_markup) -> list[Message]:
    content_type = node.get("content_type")
    entities = entities_from_json(node.get("entities_json"))
    caption_entities = entities_from_json(node.get("caption_entities_json"))
    if content_type == "text" or not content_type:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=node.get("text") or node["title"],
            entities=entities,
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "photo":
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=node["media_file_id"],
            caption=node.get("caption"),
            caption_entities=caption_entities,
            show_caption_above_media=bool(node.get("show_caption_above_media")),
            has_spoiler=bool(node.get("has_spoiler")),
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "video":
        sent = await bot.send_video(
            chat_id=chat_id,
            video=node["media_file_id"],
            caption=node.get("caption"),
            caption_entities=caption_entities,
            show_caption_above_media=bool(node.get("show_caption_above_media")),
            has_spoiler=bool(node.get("has_spoiler")),
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "animation":
        sent = await bot.send_animation(
            chat_id=chat_id,
            animation=node["media_file_id"],
            caption=node.get("caption"),
            caption_entities=caption_entities,
            show_caption_above_media=bool(node.get("show_caption_above_media")),
            has_spoiler=bool(node.get("has_spoiler")),
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "document":
        sent = await bot.send_document(
            chat_id=chat_id,
            document=node["media_file_id"],
            caption=node.get("caption"),
            caption_entities=caption_entities,
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "audio":
        sent = await bot.send_audio(
            chat_id=chat_id,
            audio=node["media_file_id"],
            caption=node.get("caption"),
            caption_entities=caption_entities,
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "voice":
        sent = await bot.send_voice(
            chat_id=chat_id,
            voice=node["media_file_id"],
            caption=node.get("caption"),
            caption_entities=caption_entities,
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "sticker":
        sent = await bot.send_sticker(
            chat_id=chat_id,
            sticker=node["media_file_id"],
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "video_note":
        sent = await bot.send_video_note(
            chat_id=chat_id,
            video_note=node["media_file_id"],
            reply_markup=reply_markup,
        )
        return [sent]
    elif content_type == "album":
        media = [_album_media_item(item) for item in get_menu_media(node["id"])]
        media = [item for item in media if item is not None]
        sent_messages = []
        if media:
            sent_messages.extend(await bot.send_media_group(chat_id=chat_id, media=media))
            if isinstance(reply_markup, ReplyKeyboardMarkup):
                sent = await bot.send_message(chat_id=chat_id, text="Меню:", reply_markup=reply_markup)
                sent_messages.append(sent)
        else:
            sent = await bot.send_message(chat_id=chat_id, text=node["title"], reply_markup=reply_markup)
            sent_messages.append(sent)
        return sent_messages
    else:
        sent = await bot.send_message(chat_id=chat_id, text=node["title"], reply_markup=reply_markup)
        return [sent]


async def send_dynamic_node(callback: CallbackQuery, node_id: int):
    node = get_menu_node(node_id)
    if not node:
        await safe_callback_answer(callback, "Кнопка не найдена.", show_alert=True)
        return

    if node.get("action") == "early_access":
        add_early_access_user(callback.from_user.id, callback.from_user.username)

    await safe_callback_answer(callback)
    try:
        await callback.message.delete()
    except Exception:
        pass

    keyboard = build_menu_keyboard(parent_id=node_id, include_back=True)
    await _send_node_content(callback.bot, callback.message.chat.id, node, keyboard)


async def send_reply_node(message: Message, node: dict[str, Any]):
    has_children = bool(list_menu_children(node["id"], menu_type="reply"))

    if node["kind"] == "url":
        set_user_reply_menu_parent(message.from_user.id, node["parent_id"])
        sent = await message.answer(node["url"], reply_markup=build_reply_menu_keyboard(node["parent_id"]))
        set_user_reply_message_ids(message.from_user.id, [sent.message_id])
        return

    set_user_reply_menu_parent(message.from_user.id, node["id"])
    keyboard = build_reply_menu_keyboard(node["id"])
    if not keyboard and not has_children:
        keyboard = build_reply_menu_keyboard(node["parent_id"])
        set_user_reply_menu_parent(message.from_user.id, node["parent_id"])
    sent_messages = await _send_node_content(message.bot, message.chat.id, node, keyboard)
    set_user_reply_message_ids(message.from_user.id, [sent.message_id for sent in sent_messages])


async def handle_reply_menu_message(message: Message) -> bool:
    if not message.from_user or not message.text:
        return False

    parent_id = get_user_reply_menu_parent(message.from_user.id)

    if message.text == REPLY_BACK_TEXT:
        current = get_menu_node(parent_id) if parent_id is not None else None
        next_parent_id = current["parent_id"] if current else None
        await delete_stored_reply_messages(message)
        await delete_processed_reply_message(message)
        set_user_reply_menu_parent(message.from_user.id, next_parent_id)
        keyboard = build_reply_menu_keyboard(next_parent_id)
        if keyboard:
            text = "Меню:" if next_parent_id is None else current["title"]
            sent = await message.answer(text, reply_markup=keyboard)
            if next_parent_id is None:
                set_user_reply_menu_message(message.from_user.id, sent.message_id)
                set_user_reply_message_ids(message.from_user.id, [])
            else:
                set_user_reply_message_ids(message.from_user.id, [sent.message_id])
            return True
        return False

    node = find_menu_child_by_title(parent_id, message.text, menu_type="reply")
    if not node and parent_id is not None:
        node = find_menu_child_by_title(None, message.text, menu_type="reply")
        if node:
            set_user_reply_menu_parent(message.from_user.id, None)
    if not node:
        return False

    await delete_stored_reply_messages(message)
    await delete_processed_reply_message(message)
    await send_reply_node(message, node)
    return True
