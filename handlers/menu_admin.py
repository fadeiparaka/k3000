"""
Админские команды для управления динамическими кнопками.
"""
import asyncio
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from config import ADMINS
from database import (
    create_menu_node,
    delete_menu_subtree,
    get_menu_node,
    get_menu_path,
    list_menu_children,
    set_setting,
    update_menu_button,
    update_menu_content,
    update_menu_url,
    replace_menu_album,
)
from menu_service import extract_album_content, extract_single_message_content

router = Router()

BTN_CANCEL = "Отмена"
BTN_BACK = "← Назад"
BTN_CREATE_HERE = "Создать здесь"
BTN_MESSAGE = "Сообщение"
BTN_URL = "Ссылка"
BTN_BLUE = "Синяя"
BTN_GREEN = "Зелёная"
BTN_RED = "Красная"
BTN_GRAY = "Серая"
BTN_EDIT_BUTTON = "Саму кнопку"
BTN_EDIT_CONTENT = "Содержимое"
BTN_EDIT_GREETING = "Приветствие"
BTN_EDIT_CHILDREN = "Вложенные кнопки"
BTN_DELETE_CURRENT = "Удалить эту кнопку"
BTN_CONFIRM_DELETE = "Да, удалить"
BTN_KEEP = "Нет, оставить"

STYLE_MAP = {
    BTN_BLUE: "primary",
    BTN_GREEN: "success",
    BTN_RED: "danger",
    BTN_GRAY: None,
}


class MenuAdminStates(StatesGroup):
    choosing_add_parent = State()
    choosing_add_kind = State()
    waiting_title = State()
    choosing_style = State()
    waiting_content = State()
    waiting_url = State()

    choosing_delete_node = State()
    confirming_delete = State()

    choosing_edit_node = State()
    choosing_edit_part = State()
    waiting_edit_title = State()
    choosing_edit_style = State()
    waiting_edit_content = State()
    waiting_edit_url = State()
    waiting_greeting = State()


_album_buffer: dict[str, list[Message]] = {}
_album_timers: set[str] = set()


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def _admin_only(message: Message) -> bool:
    return bool(message.from_user and is_admin(message.from_user.id))


def _keyboard_button(item: str | tuple[str, str | None]) -> KeyboardButton:
    if isinstance(item, tuple):
        label, style = item
    else:
        label, style = item, None
    kwargs = {"style": style} if style else {}
    return KeyboardButton(text=label, **kwargs)


def _reply_keyboard(labels: list[str | tuple[str, str | None]], columns: int = 1) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    for index in range(0, len(labels), columns):
        rows.append([_keyboard_button(label) for label in labels[index:index + columns]])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _choice_label(node: dict) -> str:
    title = node["title"]
    return title if len(title) <= 64 else f"{title[:58]}... #{node['id']}"


def _children_choices(parent_id: int | None, menu_type: str) -> tuple[list[tuple[str, str | None]], dict[str, int]]:
    labels: list[tuple[str, str | None]] = []
    mapping = {}
    for node in list_menu_children(parent_id, menu_type=menu_type):
        label = _choice_label(node)
        if label in mapping:
            label = f"{label} #{node['id']}"
        labels.append((label, node.get("style")))
        mapping[label] = node["id"]
    return labels, mapping


def _current_place(parent_id: int | None) -> str:
    if parent_id is None:
        return "приветствие"
    node = get_menu_node(parent_id)
    return node["title"] if node else "кнопка"


def _menu_type_name(menu_type: str) -> str:
    return "reply-меню" if menu_type == "reply" else "inline-меню"


def _style_buttons() -> list[tuple[str, str | None]]:
    return [
        (BTN_BLUE, "primary"),
        (BTN_GREEN, "success"),
        (BTN_RED, "danger"),
        (BTN_GRAY, None),
    ]


async def _cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Окей, отменил.", reply_markup=ReplyKeyboardRemove())


async def _ask_add_parent(message: Message, state: FSMContext):
    data = await state.get_data()
    current_parent_id = data.get("current_parent_id")
    menu_type = data.get("menu_type", "inline")
    labels, mapping = _children_choices(current_parent_id, menu_type)
    keyboard_labels: list[str | tuple[str, str | None]] = [BTN_CREATE_HERE] + labels
    if current_parent_id is not None:
        keyboard_labels.append(BTN_BACK)
    keyboard_labels.append(BTN_CANCEL)
    await state.update_data(choice_map=mapping)
    await state.set_state(MenuAdminStates.choosing_add_parent)
    await message.answer(
        f"Сейчас: {_current_place(current_parent_id)}\nГде создаём в {_menu_type_name(menu_type)}? Можно создать здесь или выбрать кнопку ниже.",
        reply_markup=_reply_keyboard(keyboard_labels)
    )


async def _ask_add_kind(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("menu_type") == "reply":
        await state.update_data(kind="message")
        await state.set_state(MenuAdminStates.waiting_title)
        await message.answer("Текст на кнопке?", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))
        return

    await state.set_state(MenuAdminStates.choosing_add_kind)
    await message.answer(
        "Создаём кнопку с сообщением или кнопку-ссылку?",
        reply_markup=_reply_keyboard([BTN_MESSAGE, BTN_URL, BTN_BACK, BTN_CANCEL])
    )


async def _ask_style(message: Message, state: FSMContext, edit: bool = False):
    await state.set_state(MenuAdminStates.choosing_edit_style if edit else MenuAdminStates.choosing_style)
    await message.answer(
        "Цвет кнопки?",
        reply_markup=_reply_keyboard(_style_buttons() + [BTN_BACK, BTN_CANCEL])
    )


def _valid_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https", "tg"} and bool(parsed.netloc or parsed.scheme == "tg")


async def _save_new_node_from_state(message: Message, state: FSMContext, content: dict | None = None, album: list[dict] | None = None):
    data = await state.get_data()
    node_id = create_menu_node(
        parent_id=data.get("parent_id"),
        title=data["title"],
        style=data.get("style"),
        kind=data["kind"],
        created_by=message.from_user.id,
        url=data.get("url"),
        menu_type=data.get("menu_type", "inline"),
    )
    if content:
        update_menu_content(node_id=node_id, updated_by=message.from_user.id, **content)
    if album:
        replace_menu_album(node_id, album, message.from_user.id)

    await state.clear()
    await message.answer(
        f"Готово. Создал кнопку: {get_menu_path(node_id)}",
        reply_markup=ReplyKeyboardRemove()
    )


async def _save_existing_content(message: Message, state: FSMContext, content: dict | None = None, album: list[dict] | None = None):
    data = await state.get_data()
    node_id = data["node_id"]
    if content:
        update_menu_content(node_id=node_id, updated_by=message.from_user.id, **content)
    if album:
        replace_menu_album(node_id, album, message.from_user.id)

    await state.clear()
    await message.answer(
        f"Готово. Обновил содержимое: {get_menu_path(node_id)}",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(Command("addbutt"))
async def cmd_add_button(message: Message, state: FSMContext):
    if not _admin_only(message):
        await message.answer("Нет прав.")
        return

    await state.clear()
    await state.update_data(menu_type="inline")
    if list_menu_children(None, menu_type="inline"):
        await state.update_data(current_parent_id=None)
        await _ask_add_parent(message, state)
    else:
        await state.update_data(parent_id=None)
        await _ask_add_kind(message, state)


@router.message(Command("addmenu"))
async def cmd_add_reply_button(message: Message, state: FSMContext):
    if not _admin_only(message):
        await message.answer("Нет прав.")
        return

    await state.clear()
    await state.update_data(menu_type="reply")
    if list_menu_children(None, menu_type="reply"):
        await state.update_data(current_parent_id=None)
        await _ask_add_parent(message, state)
    else:
        await state.update_data(parent_id=None)
        await _ask_add_kind(message, state)


@router.message(Command("delbutt"))
async def cmd_delete_button(message: Message, state: FSMContext):
    if not _admin_only(message):
        await message.answer("Нет прав.")
        return

    await state.clear()
    await state.update_data(current_parent_id=None, menu_type="inline")
    await _ask_delete_node(message, state)


@router.message(Command("delmenu"))
async def cmd_delete_reply_button(message: Message, state: FSMContext):
    if not _admin_only(message):
        await message.answer("Нет прав.")
        return

    await state.clear()
    await state.update_data(current_parent_id=None, menu_type="reply")
    await _ask_delete_node(message, state)


@router.message(Command("editbutt"))
async def cmd_edit_button(message: Message, state: FSMContext):
    if not _admin_only(message):
        await message.answer("Нет прав.")
        return

    await state.clear()
    await state.update_data(current_parent_id=None, menu_type="inline")
    await _ask_edit_node(message, state)


@router.message(Command("editmenu"))
async def cmd_edit_reply_button(message: Message, state: FSMContext):
    if not _admin_only(message):
        await message.answer("Нет прав.")
        return

    await state.clear()
    await state.update_data(current_parent_id=None, menu_type="reply")
    await _ask_edit_node(message, state)


@router.message(MenuAdminStates.choosing_add_parent, F.text)
async def choose_add_parent(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return

    data = await state.get_data()
    current_parent_id = data.get("current_parent_id")
    if message.text == BTN_BACK:
        parent = get_menu_node(current_parent_id) if current_parent_id is not None else None
        await state.update_data(current_parent_id=parent["parent_id"] if parent else None)
        await _ask_add_parent(message, state)
        return

    if message.text == BTN_CREATE_HERE:
        await state.update_data(parent_id=current_parent_id)
        await _ask_add_kind(message, state)
        return

    node_id = data.get("choice_map", {}).get(message.text)
    if not node_id:
        await message.answer("Выбери вариант кнопкой ниже.")
        return
    node = get_menu_node(node_id)
    menu_type = data.get("menu_type", "inline")
    if node and (node["kind"] == "url" or (menu_type == "inline" and node.get("content_type") == "album")):
        await message.answer("Внутри этой кнопки нельзя создать вложенные кнопки.")
        return
    await state.update_data(current_parent_id=node_id)
    await _ask_add_parent(message, state)


@router.message(MenuAdminStates.choosing_add_kind, F.text)
async def choose_add_kind(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        data = await state.get_data()
        menu_type = data.get("menu_type", "inline")
        if list_menu_children(None, menu_type=menu_type):
            await state.update_data(current_parent_id=(await state.get_data()).get("parent_id"))
            await _ask_add_parent(message, state)
        else:
            await _cancel(message, state)
        return
    if message.text not in {BTN_MESSAGE, BTN_URL}:
        await message.answer("Выбери тип кнопки.")
        return

    await state.update_data(kind="message" if message.text == BTN_MESSAGE else "url")
    await state.set_state(MenuAdminStates.waiting_title)
    await message.answer("Текст на кнопке?", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))


@router.message(MenuAdminStates.waiting_title, F.text)
async def receive_title(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await _ask_add_kind(message, state)
        return
    title = message.text.strip()
    if not title:
        await message.answer("Текст кнопки не должен быть пустым.")
        return
    await state.update_data(title=title)
    await _ask_style(message, state)


@router.message(MenuAdminStates.choosing_style, F.text)
async def choose_style(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await state.set_state(MenuAdminStates.waiting_title)
        await message.answer("Текст на кнопке?", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))
        return
    if message.text not in STYLE_MAP:
        await message.answer("Выбери цвет кнопкой ниже.")
        return

    await state.update_data(style=STYLE_MAP[message.text])
    data = await state.get_data()
    if data["kind"] == "url":
        await state.set_state(MenuAdminStates.waiting_url)
        await message.answer("Пришли ссылку.", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))
    else:
        await state.set_state(MenuAdminStates.waiting_content)
        await message.answer(
            "Что будет видно после нажатия? Пришли текст, одно медиа с подписью или альбом.",
            reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL])
        )


@router.message(MenuAdminStates.waiting_url, F.text)
async def receive_url(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await _ask_style(message, state)
        return
    url = message.text.strip()
    if not _valid_url(url):
        await message.answer("Нужна ссылка вида https://... или tg://...")
        return
    await state.update_data(url=url)
    await _save_new_node_from_state(message, state)


@router.message(MenuAdminStates.waiting_content, F.media_group_id)
async def receive_new_album(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    group_id = message.media_group_id
    _album_buffer.setdefault(group_id, []).append(message)
    if group_id in _album_timers:
        return
    _album_timers.add(group_id)
    await asyncio.sleep(0.8)
    messages = _album_buffer.pop(group_id, [])
    _album_timers.discard(group_id)
    album = extract_album_content(messages)
    if not album:
        await message.answer("Не получилось сохранить альбом. Попробуй отправить фото/видео/документы.")
        return
    await _save_new_node_from_state(message, state, album=album)


@router.message(MenuAdminStates.waiting_content)
async def receive_new_content(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await _ask_style(message, state)
        return
    content = extract_single_message_content(message)
    if not content:
        await message.answer("Пока умею сохранять текст, фото, видео, gif, документ, аудио, voice, sticker или video note.")
        return
    await _save_new_node_from_state(message, state, content=content)


async def _ask_delete_node(message: Message, state: FSMContext):
    data = await state.get_data()
    current_parent_id = data.get("current_parent_id")
    menu_type = data.get("menu_type", "inline")
    labels, mapping = _children_choices(current_parent_id, menu_type)
    keyboard_labels: list[str | tuple[str, str | None]] = []
    if current_parent_id is not None:
        keyboard_labels.append(BTN_DELETE_CURRENT)
    keyboard_labels.extend(labels)
    if current_parent_id is not None:
        keyboard_labels.append(BTN_BACK)
    keyboard_labels.append(BTN_CANCEL)
    await state.update_data(choice_map=mapping)
    await state.set_state(MenuAdminStates.choosing_delete_node)
    if labels or current_parent_id is not None:
        text = f"Сейчас: {_current_place(current_parent_id)}\nКакую кнопку удалить?"
    else:
        text = "Динамических кнопок пока нет."
    await message.answer(text, reply_markup=_reply_keyboard(keyboard_labels))


@router.message(MenuAdminStates.choosing_delete_node, F.text)
async def choose_delete_node(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return

    data = await state.get_data()
    current_parent_id = data.get("current_parent_id")
    if message.text == BTN_BACK:
        parent = get_menu_node(current_parent_id) if current_parent_id is not None else None
        await state.update_data(current_parent_id=parent["parent_id"] if parent else None)
        await _ask_delete_node(message, state)
        return

    if message.text == BTN_DELETE_CURRENT and current_parent_id is not None:
        await state.update_data(node_id=current_parent_id)
        await state.set_state(MenuAdminStates.confirming_delete)
        await message.answer(
            f"Удалить {get_menu_path(current_parent_id)} и всё внутри?",
            reply_markup=_reply_keyboard([BTN_CONFIRM_DELETE, BTN_KEEP])
        )
        return

    node_id = data.get("choice_map", {}).get(message.text)
    if not node_id:
        await message.answer("Выбери вариант кнопкой ниже.")
        return
    await state.update_data(current_parent_id=node_id)
    await _ask_delete_node(message, state)


@router.message(MenuAdminStates.confirming_delete, F.text)
async def confirm_delete_node(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_KEEP:
        await _cancel(message, state)
        return
    if message.text != BTN_CONFIRM_DELETE:
        await message.answer("Подтверди удаление кнопкой ниже.")
        return
    data = await state.get_data()
    path = get_menu_path(data["node_id"])
    delete_menu_subtree(data["node_id"])
    await state.clear()
    await message.answer(f"Удалил: {path}", reply_markup=ReplyKeyboardRemove())


async def _ask_edit_node(message: Message, state: FSMContext):
    data = await state.get_data()
    current_parent_id = data.get("current_parent_id")
    menu_type = data.get("menu_type", "inline")
    labels, mapping = _children_choices(current_parent_id, menu_type)
    keyboard_labels: list[str | tuple[str, str | None]] = []
    if current_parent_id is None and menu_type == "inline":
        keyboard_labels.append(BTN_EDIT_GREETING)
    keyboard_labels.extend(labels)
    has_choices = bool(keyboard_labels)
    if current_parent_id is not None:
        keyboard_labels.append(BTN_BACK)
    keyboard_labels.append(BTN_CANCEL)
    await state.update_data(choice_map=mapping)
    await state.set_state(MenuAdminStates.choosing_edit_node)
    if has_choices:
        text = f"Сейчас: {_current_place(current_parent_id)}\nКакую кнопку меняем?"
    else:
        text = "Динамических кнопок пока нет."
    await message.answer(text, reply_markup=_reply_keyboard(keyboard_labels))


@router.message(MenuAdminStates.choosing_edit_node, F.text)
async def choose_edit_node(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return

    data = await state.get_data()
    current_parent_id = data.get("current_parent_id")
    if message.text == BTN_BACK:
        parent = get_menu_node(current_parent_id) if current_parent_id is not None else None
        await state.update_data(current_parent_id=parent["parent_id"] if parent else None)
        await _ask_edit_node(message, state)
        return
    if message.text == BTN_EDIT_GREETING and current_parent_id is None and data.get("menu_type", "inline") == "inline":
        await state.set_state(MenuAdminStates.waiting_greeting)
        await message.answer("Пришли новый текст приветствия.", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))
        return
    node_id = data.get("choice_map", {}).get(message.text)
    if not node_id:
        await message.answer("Выбери вариант кнопкой ниже.")
        return
    await state.update_data(node_id=node_id)
    await _ask_edit_part(message, state)


async def _ask_edit_part(message: Message, state: FSMContext):
    data = await state.get_data()
    node = get_menu_node(data["node_id"])
    menu_type = data.get("menu_type", "inline")
    labels = [BTN_EDIT_BUTTON]
    if menu_type == "inline" and node and node["kind"] == "url":
        labels.append(BTN_URL)
    else:
        labels.append(BTN_EDIT_CONTENT)
    blocks_children = menu_type == "inline" and node and node.get("content_type") == "album"
    if node and node["kind"] != "url" and not blocks_children and list_menu_children(node["id"], menu_type=menu_type):
        labels.append(BTN_EDIT_CHILDREN)
    labels.extend([BTN_BACK, BTN_CANCEL])
    await state.set_state(MenuAdminStates.choosing_edit_part)
    await message.answer("Что надо изменить?", reply_markup=_reply_keyboard(labels))


@router.message(MenuAdminStates.choosing_edit_part, F.text)
async def choose_edit_part(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        data = await state.get_data()
        node = get_menu_node(data["node_id"])
        await state.update_data(current_parent_id=node["parent_id"] if node else None)
        await _ask_edit_node(message, state)
        return
    if message.text == BTN_EDIT_BUTTON:
        await state.set_state(MenuAdminStates.waiting_edit_title)
        await message.answer("Новый текст на кнопке?", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))
        return
    if message.text in {BTN_EDIT_CONTENT, BTN_URL}:
        if message.text == BTN_URL:
            await state.set_state(MenuAdminStates.waiting_edit_url)
            await message.answer("Пришли новую ссылку.", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))
        else:
            await state.set_state(MenuAdminStates.waiting_edit_content)
            await message.answer(
                "Пришли новое содержимое: текст, одно медиа с подписью или альбом.",
                reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL])
            )
        return
    if message.text == BTN_EDIT_CHILDREN:
        data = await state.get_data()
        await state.update_data(current_parent_id=data["node_id"])
        await _ask_edit_node(message, state)
        return
    await message.answer("Выбери вариант кнопкой ниже.")


@router.message(MenuAdminStates.waiting_edit_title, F.text)
async def receive_edit_title(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await _ask_edit_part(message, state)
        return
    title = message.text.strip()
    if not title:
        await message.answer("Текст кнопки не должен быть пустым.")
        return
    await state.update_data(title=title)
    await _ask_style(message, state, edit=True)


@router.message(MenuAdminStates.choosing_edit_style, F.text)
async def receive_edit_style(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await state.set_state(MenuAdminStates.waiting_edit_title)
        await message.answer("Новый текст на кнопке?", reply_markup=_reply_keyboard([BTN_BACK, BTN_CANCEL]))
        return
    if message.text not in STYLE_MAP:
        await message.answer("Выбери цвет кнопкой ниже.")
        return
    data = await state.get_data()
    update_menu_button(data["node_id"], data["title"], STYLE_MAP[message.text], message.from_user.id)
    path = get_menu_path(data["node_id"])
    await state.clear()
    await message.answer(f"Готово. Обновил кнопку: {path}", reply_markup=ReplyKeyboardRemove())


@router.message(MenuAdminStates.waiting_edit_url, F.text)
async def receive_edit_url(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await _ask_edit_part(message, state)
        return
    url = message.text.strip()
    if not _valid_url(url):
        await message.answer("Нужна ссылка вида https://... или tg://...")
        return
    data = await state.get_data()
    update_menu_url(data["node_id"], url, message.from_user.id)
    path = get_menu_path(data["node_id"])
    await state.clear()
    await message.answer(f"Готово. Обновил ссылку: {path}", reply_markup=ReplyKeyboardRemove())


@router.message(MenuAdminStates.waiting_edit_content, F.media_group_id)
async def receive_edit_album(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    group_id = message.media_group_id
    _album_buffer.setdefault(group_id, []).append(message)
    if group_id in _album_timers:
        return
    _album_timers.add(group_id)
    await asyncio.sleep(0.8)
    messages = _album_buffer.pop(group_id, [])
    _album_timers.discard(group_id)
    album = extract_album_content(messages)
    if not album:
        await message.answer("Не получилось сохранить альбом. Попробуй отправить фото/видео/документы.")
        return
    await _save_existing_content(message, state, album=album)


@router.message(MenuAdminStates.waiting_edit_content)
async def receive_edit_content(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await _ask_edit_part(message, state)
        return
    content = extract_single_message_content(message)
    if not content:
        await message.answer("Пока умею сохранять текст, фото, видео, gif, документ, аудио, voice, sticker или video note.")
        return
    await _save_existing_content(message, state, content=content)


@router.message(MenuAdminStates.waiting_greeting, F.text)
async def receive_greeting(message: Message, state: FSMContext):
    if not _admin_only(message):
        return
    if message.text == BTN_CANCEL:
        await _cancel(message, state)
        return
    if message.text == BTN_BACK:
        await state.update_data(current_parent_id=None)
        await _ask_edit_node(message, state)
        return
    greeting = message.text.strip()
    if not greeting:
        await message.answer("Приветствие не должно быть пустым.")
        return
    set_setting("main_greeting", greeting)
    await state.clear()
    await message.answer("Готово. Приветствие обновлено.", reply_markup=ReplyKeyboardRemove())
