import asyncio
import os
import random
import re
import logging
import sqlite3
import uuid
from datetime import datetime
from contextlib import closing
from enum import IntEnum
from typing import Dict, Iterable, Optional

import ai_service
from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
    BotCommand,
)
from telegram.constants import ChatAction
from telegram.error import Forbidden, TelegramError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Application,
)
from telegram.request import HTTPXRequest

from db import (
    get_conn,
    init_db,
    increment_preference_feedback,
    upsert_user_preferences,
    load_user_state,
    save_user_state,
    log_item_feedback,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN отсутствует в .env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_GEMINI_MODEL = "models/gemini-1.5-flash-latest"
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", DEFAULT_GEMINI_MODEL)
if GEMINI_API_KEY:
    ai_service.init_ai_service(GEMINI_API_KEY, GEMINI_MODEL_NAME)
else:
    logging.warning("⚠️ GEMINI_API_KEY отсутствует. Команда /ask работать не будет.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("FindFood4")

ASK_NAME, ASK_AGE, ASK_CITY = range(3)


class UserFlow(IntEnum):
    choosing_mode = 10
    choosing_category = 11
    waiting_for_input = 12
    showing_result = 13


CHOOSE_MODE = UserFlow.choosing_mode
CHOOSE_TASTE = UserFlow.choosing_category
ASK_QUERY = UserFlow.waiting_for_input
SHOW_RESULT = UserFlow.showing_result

CONTROL_BACK = "⬅️ Назад"
CONTROL_FINISH = "👋🏻 Закончить"
CONTROL_RANDOM = "🎲 Не знаю, что хочу"
CONTROL_CATEGORY_MENU = "🧭 Вернуться к выбору категории"
AI_REJECT_LIMIT = 3
AI_LOG_PATH = "ai_logs.txt"
PROCESSING_RANDOM = "processing_random"
PROCESSING_CATEGORY = "processing_category"
LAST_SUGGESTION = "last_suggestion"
SELECTED_CATEGORY_KEY = "selected_category"
SKIP_NEXT_MESSAGE = "skip_next_intro"
DEFAULT_DELAY_RANGE = (0.8, 1.2)

AI_BRIDGE_PHRASES = (
    "🥄 Думаю о чём-то вкусном…",
    "🍴 Готовлю ответ…",
    "✨ Есть идея!",
)

RECIPE_INTROS = (
    "Вот идея, которую можно попробовать 👇",
    "Давай попробуем это 👇",
    "Тебе может понравиться этот рецепт 👇",
)

PLACE_INTROS = (
    "Советую заглянуть сюда 👇",
    "Попробуй это место 👇",
    "Похоже, тебе может понравиться 👇",
)

LIKE_REPLIES = (
    "❤️ Супер! Учту твой вкус.",
    "❤️ Сохранил! Буду подбирать похожее.",
    "❤️ Добавил в твои предпочтения!",
)

FALLBACK_PREFACES = (
    "😅 Пока не нашёл ничего подходящего, но вот идея 👇",
    "🍀 Пока база молчит, держи свежий вариант 👇",
    "✨ Придумал кое-что интересное 👇",
)

CATEGORY_REACTIONS = {
    "sweet": ("🧠 Думаю о чём-то нежном и сладком…",),
    "salty": ("🧠 Хочется чего-то сытного и вкусного…",),
    "spicy": ("🧠 Что-то с огоньком, да? Сейчас подберу…",),
    "healthy": ("🧠 Думаю о чём-то лёгком и полезном…",),
}

GENERIC_REACTIONS = (
    "🧠 Думаю, что бы тебе предложить…",
    "🤔 Подбираю пару идей…",
    "✨ Сейчас что-нибудь придумаю…",
)

CATEGORY_MEDIA = {
    "sweet": "sweet.jpg",
    "salty": "salty.jpg",
    "spicy": "spicy.jpg",
    "healthy": "healthy.jpg",
    "registration": "registration.jpg",
    "hello": "hello.jpg",
    "loading": "loading.jpg",
    "not_found": "not_found.jpg",
    "farewell": "logo.jpg",
}

TASTE_TOKENS = {
    "sweet": (
        "слад", "десерт", "конд", "торт", "пирог", "пирож", "пирожн",
        "брауни", "маффин", "кекс", "cake", "sweet", "🍰"
    ),
    "salty": (
        "сол", "сыт", "основ", "salty", "🍕", "бургер", "пицца",
        "стейк", "гриль", "сендвич", "бургер", "буррито", "тако"
    ),
    "spicy": (
        "остр", "spicy", "азиат", "огонь", "🌶", "🔥", "том ям",
        "рамен", "рамэн", "лапша", "карри", "чили", "жгуч"
    ),
    "healthy": (
        "полез", "здоров", "лёгк", "легки", "овощ", "healthy", "🥗", "фитнес",
        "боул", "зож", "детокс", "салат", "овсян", "авокад"
    ),
}

MODE_TOKENS = {
    "recipe": ("🥣", "рецепт", "готов", "блюд"),
    "restaurant": ("🏙", "завед", "место", "restaurant", "кафе"),
}

SYNONYMS = {
    "чизкейк": ["cheesecake", "десерт", "sweet", "сырный торт"],
    "брауни": ["brownie", "десерт", "шоколад"],
    "десерт": ["sweet", "торт", "выпечка", "кофейня"],
    "пирог": ["шарлотка", "выпечка", "десерт"],
    "пирожное": ["десерт", "торт", "sweet"],
    "рамэн": ["рамен", "лапша", "суп", "азиатское", "спайси"],
    "рамен": ["рамэн", "лапша", "суп", "азиатское", "острое", "spicy"],
    "лапша": ["рамен", "вок", "азиатское"],
    "бургер": ["бургеры", "сэндвич", "гриль", "мясо"],
    "пицца": ["pizza", "маргарита", "итальянское", "сыр"],
    "кофе": ["кофейня", "latte", "капучино", "десерт"],
    "кофейня": ["кофе", "десерт", "sweet"],
    "кафе": ["кофейня", "coffee", "десерт", "сладкое"],
    "завтрак": ["панкейки", "омлет", "авокадо", "кофейня"],
    "салат": ["healthy", "овощи", "полезное"],
    "суп": ["борщ", "том ям", "рамэн", "лапша"],
    "роллы": ["суши", "японская", "рыба"],
    "суши": ["японская", "роллы", "азиатская", "рыба"],
    "том ям": ["тайская", "суп", "острое", "spicy"],
    "тако": ["мексиканская", "острое", "spicy"],
    "фахитас": ["мексиканская", "курица", "острое"],
    "гриль": ["барбекю", "стейк", "мясо"],
    "овсянка": ["каша", "healthy", "завтрак"],
    "боул": ["healthy", "полезное", "лёгкое"],
    "здоровое": ["healthy", "боул", "овощи"],
}

CATEGORY_HINTS = {
    "чизкейк": "sweet",
    "брауни": "sweet",
    "пирожн": "sweet",
    "пирог": "sweet",
    "торт": "sweet",
    "десерт": "sweet",
    "пирожное": "sweet",
    "кекс": "sweet",
    "маффин": "sweet",
    "кофе": "sweet",
    "кофей": "sweet",
    "sweet": "sweet",
    "dessert": "sweet",
    "сладкий": "sweet",
    "сладкая": "sweet",
    "сладкое": "sweet",
    "сладень": "sweet",
    "рамэн": "spicy",
    "рамен": "spicy",
    "лапша": "spicy",
    "том ям": "spicy",
    "чили": "spicy",
    "spicy": "spicy",
    "спайси": "spicy",
    "азиат": "spicy",
    "азиатск": "spicy",
    "острый": "spicy",
    "острое": "spicy",
    "острень": "spicy",
    "бургер": "salty",
    "пицца": "salty",
    "буррито": "salty",
    "тако": "salty",
    "стейк": "salty",
    "гриль": "salty",
    "солен": "salty",
    "солён": "salty",
    "сытн": "salty",
    "боул": "healthy",
    "салат": "healthy",
    "овсян": "healthy",
    "авокад": "healthy",
    "здоровое": "healthy",
    "здоровый": "healthy",
    "здоровая": "healthy",
    "полезное": "healthy",
    "полезный": "healthy",
    "полезная": "healthy",
    "фитнес": "healthy",
    "healthy": "healthy",
}

DEFAULT_TASTES = ("sweet", "salty", "spicy", "healthy")

USER_STATE: Dict[int, Dict[str, Optional[str]]] = {}


async def cozy_delay():
    await asyncio.sleep(random.uniform(*DEFAULT_DELAY_RANGE))


def limit_paragraph_length(paragraph: str, max_len: int = 150) -> str:
    text = (paragraph or "").strip()
    if len(text) <= max_len:
        return text
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return "\n".join(filter(None, chunks))


def prepare_ai_response(raw: str) -> str:
    if not raw:
        return ""
    primary_block = raw.strip().split("\n\n")[0].strip()
    lines = [line.strip() for line in primary_block.split("\n") if line.strip()]
    if not lines:
        return limit_paragraph_length(primary_block)
    deduped: list[str] = []
    for line in lines:
        formatted = limit_paragraph_length(line)
        if formatted and (not deduped or formatted != deduped[-1]):
            deduped.append(formatted)
        if len(deduped) == 3:
            break
    return "\n\n".join(deduped[:3])


def pick_bridge_phrase() -> str:
    return random.choice(AI_BRIDGE_PHRASES)


def ensure_user_state(user_id: int) -> Dict[str, Optional[str]]:
    if user_id not in USER_STATE:
        stored = load_user_state(user_id)
        USER_STATE[user_id] = {
            "mode": stored.get("mode"),
            "category": stored.get("category"),
            "city": stored.get("city"),
            "last_action": stored.get("last_action"),
            "last_query": None,
            "last_choice": None,
            PROCESSING_RANDOM: False,
            PROCESSING_CATEGORY: False,
        }
    return USER_STATE[user_id]


def remember_context(
    user_id: int,
    *,
    mode: Optional[str] = None,
    category: Optional[str] = None,
    city: Optional[str] = None,
    query: Optional[str] = None,
    last_choice: Optional[str] = None,
    last_action: Optional[str] = None,
):
    state = ensure_user_state(user_id)
    if mode is not None:
        state["mode"] = mode
    if category is not None:
        state["category"] = category
    if city is not None:
        canonical_city = canonicalize_city(city)
        state["city"] = canonical_city
        city = canonical_city
    if query is not None:
        state["last_query"] = query
    if last_choice is not None:
        state["last_choice"] = last_choice
    if last_action is not None:
        state["last_action"] = last_action

    persistence_kwargs = {}
    if mode is not None:
        persistence_kwargs["mode"] = mode
    if category is not None:
        persistence_kwargs["category"] = category
    if city is not None:
        persistence_kwargs["city"] = city
    if last_action is not None:
        persistence_kwargs["last_action"] = last_action
    if persistence_kwargs:
        try:
            save_user_state(user_id, **persistence_kwargs)
        except sqlite3.Error as exc:
            log.warning("Не удалось обновить user_state: %s", exc)

    try:
        if any(value is not None for value in (mode, category, query)):
            upsert_user_preferences(user_id, mode=mode, category=category, query=query)
    except sqlite3.Error as exc:
        log.warning("Не удалось обновить user_preferences: %s", exc)

    snapshot = ensure_user_state(user_id)
    print(
        f"[STATE] user_id={user_id}, mode={snapshot.get('mode')}, "
        f"category={snapshot.get('category')}, city={snapshot.get('city')}, "
        f"last_action={snapshot.get('last_action')}"
    )


def set_processing_random(user_id: int, value: bool):
    state = ensure_user_state(user_id)
    state[PROCESSING_RANDOM] = value


def is_processing_random(user_id: int) -> bool:
    return ensure_user_state(user_id).get(PROCESSING_RANDOM, False)


def set_processing_category(user_id: int, value: bool):
    state = ensure_user_state(user_id)
    state[PROCESSING_CATEGORY] = value


def is_processing_category(user_id: int) -> bool:
    return ensure_user_state(user_id).get(PROCESSING_CATEGORY, False)


async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    if isinstance(err, TimedOut):
        log.warning("Network timeout while calling Telegram API: %s", err)
        return
    log.exception("Unhandled error during update processing", exc_info=err)


def get_last_suggestions(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault(LAST_SUGGESTION, {"recipe": None, "place": None})


def update_last_suggestion(context: ContextTypes.DEFAULT_TYPE, item_type: str, item_id):
    suggestions = get_last_suggestions(context)
    suggestions[item_type] = item_id


def is_last_suggestion(context: ContextTypes.DEFAULT_TYPE, item_type: str, item_id) -> bool:
    suggestions = get_last_suggestions(context)
    return suggestions.get(item_type) == item_id


def suggestion_id(item: Optional[dict]) -> Optional[int]:
    if not item:
        return None
    return item.get("id")


def log_ai_interaction(user_id: int, question: str, answer: str, status: str):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT INTO ai_logs(user_id, question, answer, status)
            VALUES (?,?,?,?)
            """,
            (user_id, question, answer, status),
        )
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(AI_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] User {user_id} → Prompt: \"{question}\"\n")
            if answer:
                log_file.write(f"AI → Answer ({status}): \"{answer}\"\n\n")
            else:
                log_file.write(f"AI → Answer ({status}): <empty>\n\n")
    except OSError as exc:
        log.warning("Не удалось записать ai_logs.txt: %s", exc)


def save_ai_feedback(question: str, answer: str, user_id: int, liked: int):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT INTO ai_feedback(question, answer, user_id, liked)
            VALUES (?,?,?,?)
            """,
            (question, answer, user_id, liked),
        )


def save_qa_entry(question: str, answer: str):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO qa(question, answer)
            VALUES(?,?)
            """,
            (question, answer),
        )


def fetch_qa_answer(question: str):
    norm = normalize(question)
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT answer, image FROM qa WHERE lower(question)=?",
            (norm,),
        ).fetchone()
    return row


def ai_feedback_keyboard(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👍 Нравится", callback_data=f"ai_like|{session_id}"),
                InlineKeyboardButton("👎 Не нравится", callback_data=f"ai_dislike|{session_id}"),
                InlineKeyboardButton("🔁 Следующее", callback_data=f"ai_next|{session_id}"),
            ]
        ]
    )


def get_ai_sessions(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.chat_data.setdefault("ai_sessions", {})


def build_refinement_prompt(question: str, previous_answer: str) -> str:
    return (
        f"{question.strip()}\n\n"
        f"Предыдущий ответ был не принят пользователем:\n\"{previous_answer.strip()}\".\n"
        "Переформулируй ответ, сделай его короче, понятнее и более полезным. "
        "Если в вопросе о еде, добавь конкретные идеи. Ответь дружелюбно на русском языке."
    )


async def generate_ai_answer(prompt: str, user_id: int, original_question: str, *, mode: str = "default") -> str:
    if not ai_service.is_ai_available():
        raise RuntimeError("Gemini API не настроен.")

    try:
        answer = await ai_service.ask_ai(prompt, mode=mode)
        status = "success" if answer else "empty"
        log_ai_interaction(user_id, original_question, answer, status)
        if not answer:
            raise RuntimeError("Модель не вернула текста.")
        return answer
    except Exception as exc:
        log_ai_interaction(user_id, original_question, "", f"error: {exc}")
        message = str(exc)
        if "404" in message and "models" in message:
            raise RuntimeError(
                "Модель недоступна. Укажи актуальное имя в GEMINI_MODEL_NAME, например 'models/gemini-1.5-flash-latest'."
            ) from exc
        raise


def normalize(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def canonicalize_city(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = (raw or "").strip()
    if not text:
        return None
    norm = normalize(text)
    if not norm:
        return text
    try:
        with closing(get_conn()) as conn:
            rows = conn.execute("SELECT DISTINCT city FROM restaurants WHERE city IS NOT NULL").fetchall()
    except sqlite3.Error:
        rows = []
    norm_map = {normalize(row["city"]): row["city"] for row in rows if row["city"]}
    direct = norm_map.get(norm)
    if direct:
        return direct
    for city_norm, original in norm_map.items():
        if city_norm in norm or norm in city_norm:
            return original
    return text.title()


def resolve_mode(text: str) -> Optional[str]:
    t = normalize(text)
    for mode, tokens in MODE_TOKENS.items():
        if any(token in t for token in tokens):
            return mode
    return None


def resolve_category(text: str) -> Optional[str]:
    t = normalize(text)
    if not t:
        return None
    if "не знаю" in t or "random" in t or "🎲" in text:
        return "random"
    for cat, tokens in TASTE_TOKENS.items():
        if any(token in t for token in tokens):
            return cat
    return None


def expand_terms(query: str) -> list[str]:
    base = normalize(query)
    if not base:
        return []
    terms = set([base])
    for key, group in SYNONYMS.items():
        if key in base:
            terms.update(group)
        if base == key:
            terms.update(group)
        if base in group:
            terms.add(key)
            terms.update(group)
    terms.update(base.split())
    terms.update({base.rstrip(suffix) for suffix in ("ы", "а", "ой", "ий", "я", "ь") if base.endswith(suffix)})
    try:
        with closing(get_conn()) as conn:
            rows = conn.execute("SELECT word, alt_words FROM synonyms").fetchall()
        for row in rows:
            word = normalize(row["word"])
            if not word:
                continue
            alts = [normalize(w) for w in (row["alt_words"] or "").split(",") if w]
            if word in base or base in word:
                terms.add(word)
                terms.update(alts)
            if base in alts:
                terms.add(word)
                terms.update(alts)
    except sqlite3.Error:
        pass
    return [t for t in terms if t]


def get_media_path(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    path = os.path.join("images", name)
    if os.path.exists(path):
        return path
    if name == "logo.jpg":
        fallback = os.path.join("images", "happy.png")
        return fallback if os.path.exists(fallback) else None
    return None


async def send_text_safely(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    """Telegram API ограничивает сообщения ~4096 символами."""

    max_len = 3900  # небольшое окно для подписи/эмодзи
    if len(text) <= max_len:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        return

    chunks = []
    current = []
    length = 0
    for paragraph in text.split("\n"):
        paragraph_with_break = (paragraph + "\n") if paragraph else "\n"
        if length + len(paragraph_with_break) > max_len and current:
            chunks.append("".join(current))
            current = []
            length = 0
        current.append(paragraph_with_break)
        length += len(paragraph_with_break)
    if current:
        chunks.append("".join(current))

    for i, chunk in enumerate(chunks):
        await context.bot.send_message(
            chat_id=chat_id,
            text=chunk,
            reply_markup=reply_markup if i == len(chunks) - 1 else None,
        )


async def send_visual(context: ContextTypes.DEFAULT_TYPE, chat_id: int, image: Optional[str], text: Optional[str],
                      reply_markup=None):
    path = get_media_path(image)
    try:
        if path:
            with open(path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo, filename=os.path.basename(path)),
                    caption=text,
                    reply_markup=reply_markup,
                )
        elif text:
            await send_text_safely(context, chat_id, text, reply_markup=reply_markup)
    except Forbidden:
        log.warning("Cannot send to chat %s – bot blocked or not started.", chat_id)
    except TelegramError as exc:
        log.exception("Failed to send visual to %s: %s", chat_id, exc)


async def send_thinking(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str = "🤔 Думаю, что тебе предложить…", notify: bool = False):
    try:
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        if notify and text:
            await send_text_safely(context, chat_id, text)
        await asyncio.sleep(0.4)
    except Forbidden:
        log.warning("Cannot notify chat %s – bot blocked or not started.", chat_id)
    except TelegramError as exc:
        log.exception("Failed to send typing notice to %s: %s", chat_id, exc)


async def ask_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args or []).strip()
    if not question:
        await update.message.reply_text(
            "Задай вопрос вместе с командой, например:\n"
            "/ask Какой десерт быстро приготовить?"
        )
        return
    await handle_ai_question(update, context, question, direct_mode=True)


async def handle_ai_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    question: str,
    *,
    session_id: Optional[str] = None,
    direct_mode: bool = False,
):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id

    if not session_id and not direct_mode:
        row = fetch_qa_answer(question)
        if row:
            answer, image = row["answer"], row["image"]
            prefix = "Нашёл ответ в базе знаний 👇\n\n"
            if image:
                await send_visual(context, chat_id, image, prefix + answer)
            else:
                await send_text_safely(context, chat_id, prefix + answer)
            return

    if not ai_service.is_ai_available():
        await send_text_safely(context, chat_id, "⚠️ ИИ недоступен. Проверь ключ GEMINI_API_KEY.")
        return

    sessions = get_ai_sessions(context)
    prev_session = sessions.get(session_id) if session_id else None
    if prev_session:
        direct_mode = prev_session.get("direct_mode", direct_mode)
    if prev_session:
        question_for_ai = prev_session["question"]
    else:
        question_for_ai = question

    if direct_mode:
        if prev_session:
            prompt = ai_service.build_direct_refinement_prompt(question_for_ai, prev_session["answer"])
        else:
            prompt = ai_service.build_direct_prompt(question)
    else:
        refined_prompt = build_refinement_prompt(question_for_ai, prev_session["answer"] if prev_session else "") if prev_session else None
        prompt = refined_prompt or question_for_ai

    try:
        answer = await generate_ai_answer(
            prompt,
            chat_id,
            question_for_ai,
            mode="structured" if direct_mode else "default",
        )
    except Exception as exc:
        log.warning("/ask failed: %s", exc)
        await send_text_safely(
            context,
            chat_id,
            "⚠️ Не удалось получить ответ. Попробуем снова чуть позже.",
        )
        return

    session_id = session_id or str(uuid.uuid4())
    session_record = {
        "question": question_for_ai,
        "answer": answer,
        "rejections": prev_session["rejections"] if prev_session else 0,
        "direct_mode": direct_mode,
    }
    sessions[session_id] = session_record

    if direct_mode:
        payload = ai_service.clean_structured_text(answer)
        await send_text_safely(
            context,
            chat_id,
            payload,
            reply_markup=ai_feedback_keyboard(session_id),
        )
    else:
        formatted = prepare_ai_response(answer)
        paragraphs = [part.strip() for part in formatted.split("\n\n") if part.strip()] if formatted else []
        if paragraphs:
            paragraphs[0] = f"{pick_bridge_phrase()}\n{paragraphs[0]}"
        else:
            paragraphs = [pick_bridge_phrase()]
        payload = "\n\n".join(paragraphs)
        await send_text_safely(
            context,
            chat_id,
            payload,
            reply_markup=ai_feedback_keyboard(session_id),
        )


async def ai_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if "|" not in data:
        return
    action, session_id = data.split("|", 1)
    sessions = get_ai_sessions(context)
    session = sessions.get(session_id)
    if not session:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("Сессия не найдена. Попробуй спросить ещё раз 🤖")
        return

    question = session["question"]
    answer = session["answer"]
    user_id = query.from_user.id

    if action == "ai_like":
        save_ai_feedback(question, answer, user_id, 1)
        save_qa_entry(question, answer)
        update_taste_profile_from_text(user_id, f"{question} {answer}", True)
        sessions.pop(session_id, None)
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("❤️ Спасибо! Я запомнил этот ответ.")
        return

    if action == "ai_dislike":
        save_ai_feedback(question, answer, user_id, 0)
        update_taste_profile_from_text(user_id, f"{question} {answer}", False)
        session["rejections"] = session.get("rejections", 0) + 1
        if session["rejections"] >= AI_REJECT_LIMIT:
            sessions.pop(session_id, None)
            await query.edit_message_reply_markup(None)
            await query.message.reply_text(
                "😔 Не удалось подобрать подходящий ответ. Попробуй переформулировать вопрос или обратись к оператору."
            )
            return
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("Понял, попробую сформулировать по-другому 🔄")
        await handle_ai_question(update, context, question, session_id=session_id)
        return

    if action == "ai_next":
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("Хорошо, предложу другой вариант 🔄")
        await handle_ai_question(update, context, question, session_id=session_id)
        return


def reset_session(context: ContextTypes.DEFAULT_TYPE):
    preserved = context.user_data.get("hinted_categories", set())
    context.user_data.clear()
    if preserved:
        context.user_data["hinted_categories"] = preserved


def set_selected_category(context: ContextTypes.DEFAULT_TYPE, category: Optional[str]):
    if category:
        context.user_data[SELECTED_CATEGORY_KEY] = category
    else:
        context.user_data.pop(SELECTED_CATEGORY_KEY, None)


def get_selected_category(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    return context.user_data.get(SELECTED_CATEGORY_KEY)


def get_user(chat_id: int):
    with closing(get_conn()) as conn:
        return conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()


def upsert_user(chat_id: int, name: str, age: int, city: str):
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT INTO users(chat_id, name, age, city)
            VALUES(?,?,?,?)
            ON CONFLICT(chat_id) DO UPDATE SET
                name=excluded.name,
                age=excluded.age,
                city=excluded.city
            """,
            (chat_id, name, age, city),
        )


def ensure_synonyms():
    with closing(get_conn()) as conn, conn:
        for word, alts in SYNONYMS.items():
            conn.execute(
                "INSERT OR IGNORE INTO synonyms(word, alt_words) VALUES(?,?)",
                (word, ",".join(alts)),
            )


def detect_category_from_text(*values: Optional[str]) -> Optional[str]:
    chunks: list[str] = []
    for value in values:
        if value:
            chunks.append(str(value))
    text = " ".join(chunks).strip().lower()
    if not text:
        return None
    compact = text.replace(" ", "")
    for cat, tokens in TASTE_TOKENS.items():
        for token in tokens:
            normalized_token = token.strip().lower().replace(" ", "")
            if normalized_token and normalized_token in compact:
                return cat
    for hint, cat in CATEGORY_HINTS.items():
        normalized_hint = hint.strip().lower()
        if normalized_hint and normalized_hint in text:
            return cat
    words = (
        text.replace(";", " ")
        .replace(",", " ")
        .replace(".", " ")
        .replace("!", " ")
        .replace("?", " ")
        .split()
    )
    for word in words:
        norm = word.strip()
        if not norm:
            continue
        for hint, cat in CATEGORY_HINTS.items():
            normalized_hint = hint.strip().lower()
            if normalized_hint and normalized_hint in norm:
                return cat
        synonyms = SYNONYMS.get(norm)
        if synonyms:
            for syn in synonyms:
                syn_norm = syn.strip().lower()
                for hint, cat in CATEGORY_HINTS.items():
                    normalized_hint = hint.strip().lower()
                    if normalized_hint and normalized_hint in syn_norm:
                        return cat
    return None


def taste_keyboard() -> ReplyKeyboardMarkup:
    keys = [
        [KeyboardButton("🍰 Сладкое"), KeyboardButton("🍕 Солёное")],
        [KeyboardButton("🌶 Острое"), KeyboardButton("🥗 Полезное")],
        [KeyboardButton(CONTROL_RANDOM)],
        [KeyboardButton(CONTROL_BACK)],
    ]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True, one_time_keyboard=False)


def mode_keyboard() -> ReplyKeyboardMarkup:
    keys = [
        [KeyboardButton("🥣 Хочу рецепт"), KeyboardButton("🏙️ Хочу заведение")],
        [KeyboardButton(CONTROL_RANDOM)],
        [KeyboardButton(CONTROL_FINISH)],
    ]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True, one_time_keyboard=True)


def query_keyboard() -> ReplyKeyboardMarkup:
    keys = [
        [KeyboardButton(CONTROL_RANDOM)],
        [KeyboardButton(CONTROL_CATEGORY_MENU)],
        [KeyboardButton(CONTROL_BACK), KeyboardButton(CONTROL_FINISH)],
    ]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)


def taste_label(cat: Optional[str]) -> str:
    return {
        "sweet": "чего-то сладенького",
        "salty": "чего-то сытного",
        "spicy": "остренького",
        "healthy": "полезного и лёгкого",
    }.get(cat or "", "чего-то вкусного")


def category_short_label(cat: Optional[str]) -> str:
    return {
        "sweet": "сладкое",
        "salty": "солёное",
        "spicy": "острое",
        "healthy": "здоровое",
    }.get(cat or "", "любую еду")


def taste_prompt_label(cat: Optional[str]) -> str:
    return {
        "sweet": "sweet dessert",
        "salty": "savory dish",
        "spicy": "spicy meal",
        "healthy": "healthy recipe",
    }.get(cat or "", "comfort food")


def reaction_message(category: Optional[str]) -> str:
    options = CATEGORY_REACTIONS.get(category)
    if options:
        return random.choice(options)
    return random.choice(GENERIC_REACTIONS)


def store_queue(context: ContextTypes.DEFAULT_TYPE, item_type: str, items: Iterable[dict], meta: dict):
    context.user_data[f"{item_type}_bundle"] = {"items": list(items), "index": 0, "meta": meta}


def current_item(context: ContextTypes.DEFAULT_TYPE, item_type: str) -> Optional[dict]:
    bundle = context.user_data.get(f"{item_type}_bundle")
    if not bundle:
        return None
    items = bundle.get("items") or []
    idx = bundle.get("index", 0)
    return items[idx] if idx < len(items) else None


def advance_queue(context: ContextTypes.DEFAULT_TYPE, item_type: str):
    bundle = context.user_data.get(f"{item_type}_bundle")
    if not bundle:
        return
    bundle["index"] = bundle.get("index", 0) + 1


def queue_meta(context: ContextTypes.DEFAULT_TYPE, item_type: str) -> dict:
    bundle = context.user_data.get(f"{item_type}_bundle") or {}
    return bundle.get("meta") or {}


def row_dict(row) -> dict:
    return dict(row) if row else {}


def resolve_random_category(conn, chat_id: int, fallback: Optional[str]) -> Optional[str]:
    if fallback and fallback != "random":
        return fallback
    row = conn.execute(
        """
        SELECT category, (likes - dislikes) AS score, likes
        FROM user_tastes
        WHERE chat_id=?
        ORDER BY score DESC, likes DESC
        LIMIT 1
        """,
        (chat_id,),
    ).fetchone()
    if row and (row["score"] or 0) >= 0 and row["likes"] >= 1:
        return row["category"]
    if fallback and fallback != "random":
        return fallback
    return random.choice(DEFAULT_TASTES)


def fetch_recipes(
    conn,
    terms: list[str],
    taste: Optional[str],
    limit: int = 3,
    primary: Optional[str] = None,
    selected_category: Optional[str] = None,
):
    clauses = []
    filter_params: list = []
    if terms:
        term_clauses = []
        for term in terms:
            norm = normalize(term)
            if not norm:
                continue
            like = f"%{norm}%"
            term_clauses.append("(lower(title) LIKE ? OR lower(tags) LIKE ? OR lower(keywords) LIKE ?)")
            filter_params.extend([like, like, like])
        clauses.append("(" + " OR ".join(term_clauses) + ")")
    category_filter = selected_category or (taste if taste and taste != "random" else None)
    fallback_clause = None
    fallback_params: list = []
    if category_filter:
        normalized_category = category_filter.lower()
        clauses.append("LOWER(category)=?")
        filter_params.append(normalized_category)
        like = f"%{normalized_category}%"
        fallback_clause = "(LOWER(category) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(keywords) LIKE ?)"
        fallback_params = [like, like, like]
    score_expr = "0"
    score_params: list = []
    primary_norm = normalize(primary) if primary else ""
    if primary_norm:
        like = f"%{primary_norm}%"
        score_expr = "(CASE WHEN lower(title) LIKE ? THEN 3 WHEN lower(tags) LIKE ? THEN 2 WHEN lower(keywords) LIKE ? THEN 1 ELSE 0 END)"
        score_params = [like, like, like]

    def run_query(active_clauses: list[str], active_params: list) -> list[dict]:
        where = "WHERE " + " AND ".join(active_clauses) if active_clauses else ""
        sql = f"SELECT *, {score_expr} AS match_score FROM recipes {where} ORDER BY match_score DESC, likes DESC, RANDOM() LIMIT ?"
        params = score_params + active_params + [limit]
        return list(map(row_dict, conn.execute(sql, params).fetchall()))

    rows = run_query(clauses, filter_params)
    if rows or not category_filter or selected_category or not fallback_clause:
        return rows

    fallback_clauses = clauses[:-1]
    fallback_params_all = filter_params[:-1]
    fallback_clauses.append(fallback_clause)
    fallback_params_all.extend(fallback_params)
    return run_query(fallback_clauses, fallback_params_all)


def fetch_restaurants(
    conn,
    city: str,
    terms: list[str],
    taste: Optional[str],
    limit: int = 3,
    primary: Optional[str] = None,
    selected_category: Optional[str] = None,
):
    clauses = []
    filter_params: list = []
    if city:
        clauses.append("city=?")
        filter_params.append(city)
    taste_hints = {
        "sweet": ["слад", "десерт", "кофе", "кофей", "sweet"],
        "salty": ["сол", "сыт", "гриль", "бургер", "пицц", "salty"],
        "spicy": ["остр", "чили", "азиат", "spicy", "огн"],
        "healthy": ["полез", "здоров", "боул", "овощ", "healthy"],
    }
    if terms:
        term_clauses = []
        for term in terms:
            norm = normalize(term)
            if not norm:
                continue
            like = f"%{norm}%"
            term_clauses.append("(lower(name) LIKE ? OR lower(tags) LIKE ? OR lower(keywords) LIKE ? OR lower(cuisine) LIKE ?)")
            filter_params.extend([like, like, like, like])
        clauses.append("(" + " OR ".join(term_clauses) + ")")
    category_filter = selected_category or (taste if taste and taste != "random" else None)
    fallback_clause = None
    fallback_params: list = []
    if category_filter:
        normalized_category = category_filter.lower()
        clauses.append("LOWER(category)=?")
        filter_params.append(normalized_category)
        like = f"%{normalized_category}%"
        fallback_clause = "(LOWER(category) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(keywords) LIKE ? OR LOWER(cuisine) LIKE ?)"
        fallback_params = [like, like, like, like]
    elif taste and taste != "random":
        hints = taste_hints.get(taste, [taste])
        hint_clauses = []
        for hint in hints:
            norm = normalize(hint)
            if not norm:
                continue
            like = f"%{norm}%"
            hint_clauses.append("(lower(tags) LIKE ? OR lower(keywords) LIKE ? OR lower(cuisine) LIKE ?)")
            filter_params.extend([like, like, like])
        clauses.append("(" + " OR ".join(hint_clauses) + ")")
    if not clauses:
        clauses.append("1=1")
    score_expr = "0"
    score_params: list = []
    primary_norm = normalize(primary) if primary else ""
    if primary_norm:
        like = f"%{primary_norm}%"
        score_expr = "(CASE WHEN lower(name) LIKE ? THEN 3 WHEN lower(tags) LIKE ? THEN 2 WHEN lower(keywords) LIKE ? THEN 1 ELSE 0 END)"
        score_params = [like, like, like]

    def run_query(active_clauses: list[str], active_params: list) -> list[dict]:
        where = "WHERE " + " AND ".join(active_clauses)
        sql = f"SELECT *, {score_expr} AS match_score FROM restaurants {where} ORDER BY match_score DESC, rating DESC, RANDOM() LIMIT ?"
        params = score_params + active_params + [limit]
        return list(map(row_dict, conn.execute(sql, params).fetchall()))

    rows = run_query(clauses, filter_params)
    if rows or not category_filter or selected_category or not fallback_clause:
        return rows

    fallback_clauses = clauses[:-1]
    fallback_params_all = filter_params[:-1]
    fallback_clauses.append(fallback_clause)
    fallback_params_all.extend(fallback_params)
    return run_query(fallback_clauses, fallback_params_all)


def fetch_random_recipe(
    conn,
    chat_id: int,
    taste: Optional[str],
    *,
    selected_category: Optional[str] = None,
) -> Optional[dict]:
    category = selected_category or resolve_random_category(conn, chat_id, taste)
    clauses: list[str] = []
    params: list = []
    if category and category != "random":
        clauses.append("LOWER(category)=?")
        params.append(category.lower())
    base_sql = "SELECT * FROM recipes"
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    row = conn.execute(f"{base_sql}{where} ORDER BY RANDOM() LIMIT 1", params).fetchone()
    if not row and category and category != "random" and not selected_category:
        clauses_without_category = clauses[:-1]
        params_without_category = params[:-1]
        like = f"%{category.lower()}%"
        fallback_clause = "(LOWER(category) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(keywords) LIKE ?)"
        clauses_without_category.append(fallback_clause)
        params_without_category.extend([like, like, like])
        where = " WHERE " + " AND ".join(clauses_without_category) if clauses_without_category else ""
        row = conn.execute(f"{base_sql}{where} ORDER BY RANDOM() LIMIT 1", params_without_category).fetchone()
    data = row_dict(row)
    if data:
        if not data.get("category"):
            detected_category = detect_category_from_text(data.get("tags"), data.get("keywords"))
            if category and category != "random":
                data["category"] = category
            elif detected_category:
                data["category"] = detected_category
        elif category and category != "random":
            data["category"] = category
    return data


def fetch_random_place(
    conn,
    chat_id: int,
    city: str,
    taste: Optional[str],
    *,
    selected_category: Optional[str] = None,
) -> Optional[dict]:
    category = selected_category or resolve_random_category(conn, chat_id, taste)

    clauses = []
    params: list = []

    if city:
        clauses.append("city=?")
        params.append(city)
    else:
        clauses.append("1=1")

    if category and category != "random":
        clauses.append("LOWER(category)=?")
        params.append(category.lower())

    base_sql = "SELECT * FROM restaurants WHERE " + " AND ".join(clauses)

    if category and category != "random":
        row = conn.execute(base_sql + " ORDER BY rating DESC, RANDOM() LIMIT 1", params).fetchone()
        if not row and not selected_category:
            clauses_without_category = clauses[:-1]
            params_without_category = params[:-1]
            like = f"%{category.lower()}%"
            fallback_clause = "(LOWER(category) LIKE ? OR LOWER(tags) LIKE ? OR LOWER(keywords) LIKE ? OR LOWER(cuisine) LIKE ?)"
            clauses_without_category.append(fallback_clause)
            params_without_category.extend([like, like, like, like])
            fallback_sql = "SELECT * FROM restaurants WHERE " + " AND ".join(clauses_without_category)
            row = conn.execute(fallback_sql + " ORDER BY rating DESC, RANDOM() LIMIT 1", params_without_category).fetchone()
    else:
        row = conn.execute(base_sql + " ORDER BY rating DESC, RANDOM() LIMIT 1", params).fetchone()

    # ⛔ ВАЖНО: не прыгать на другие города/категории, если в этом городе ничего нет
    if not row:
        return None

    data = row_dict(row)
    if data:
        if not data.get("category"):
            detected_category = detect_category_from_text(data.get("tags"), data.get("keywords"))
            if category and category != "random":
                data["category"] = category
            elif detected_category:
                data["category"] = detected_category
        elif category and category != "random":
            data["category"] = category
    return data


def apply_feedback(conn, chat_id: int, item: dict, item_type: str, liked: bool):
    if not item:
        return
    raw_category = item.get("category")
    primary_category = raw_category.strip() if isinstance(raw_category, str) else raw_category
    category = primary_category or detect_category_from_text(item.get("category"), item.get("tags"), item.get("keywords"))
    if category:
        conn.execute(
            """
            INSERT INTO user_history(chat_id, item_id, item_type, category, liked)
            VALUES (?,?,?,?,?)
            """,
            (chat_id, item.get("id"), item_type, category, 1 if liked else 0),
        )
        conn.execute(
            """
            INSERT INTO user_tastes(chat_id, category, likes, dislikes)
            VALUES (?,?,?,?)
            ON CONFLICT(chat_id, category) DO UPDATE SET
                likes = likes + excluded.likes,
                dislikes = dislikes + excluded.dislikes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, category, 1 if liked else 0, 0 if liked else 1),
        )
    if item_type == "recipe":
        if liked:
            conn.execute(
                "INSERT OR IGNORE INTO favorites(chat_id, recipe_id) VALUES(?,?)",
                (chat_id, item.get("id")),
        )
        conn.execute(
            "UPDATE recipes SET likes = likes + ? WHERE id=?",
            (1 if liked else 0, item.get("id")),
        )
    try:
        increment_preference_feedback(chat_id, liked, conn=conn)
    except sqlite3.Error as exc:
        log.warning("Не удалось обновить user_preferences по фидбеку: %s", exc)


def update_taste_profile_from_text(chat_id: int, text: str, liked: bool):
    category = detect_category_from_text(text)
    if not category:
        return
    with closing(get_conn()) as conn, conn:
        conn.execute(
            """
            INSERT INTO user_tastes(chat_id, category, likes, dislikes)
            VALUES (?,?,?,?)
            ON CONFLICT(chat_id, category) DO UPDATE SET
                likes = likes + excluded.likes,
                dislikes = dislikes + excluded.dislikes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (chat_id, category, 1 if liked else 0, 0 if liked else 1),
        )


def fetch_recipe_by_id(conn, rid: int) -> Optional[dict]:
    return row_dict(conn.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone())


def fetch_restaurant_by_id(conn, rid: int) -> Optional[dict]:
    return row_dict(conn.execute("SELECT * FROM restaurants WHERE id=?", (rid,)).fetchone())


def top_taste(conn, chat_id: int) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT category, likes, dislikes
        FROM user_tastes
        WHERE chat_id=?
        ORDER BY likes DESC
        LIMIT 1
        """,
        (chat_id,),
    ).fetchone()
    if row and row["likes"] >= 5 and row["likes"] > row["dislikes"]:
        return row_dict(row)
    return None


async def maybe_send_hint(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    hinted = context.user_data.setdefault("hinted_categories", set())
    with closing(get_conn()) as conn:
        info = top_taste(conn, chat_id)
    if not info:
        return
    category = info["category"]
    if category in hinted:
        return
    hinted.add(category)
    label = {
        "sweet": "десерты и всё молочное",
        "salty": "сытные блюда",
        "spicy": "острые блюда",
        "healthy": "лёгкая и полезная еда",
    }.get(category, category)
    await send_text_safely(
        context,
        chat_id,
        f"🧠 Похоже, тебе нравится {label}!\nХочешь, подберу 3 новинки в этом вкусе?",
        reply_markup=query_keyboard(),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    ensure_synonyms()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    ensure_user_state(user_id)
    reset_session(context)
    user = get_user(chat_id)
    if not user:
        await send_visual(
            context,
            chat_id,
            CATEGORY_MEDIA["registration"],
            "Привет! 👋🏻 Я FindFood, твой гид по еде 🍴\nКак тебя зовут?",
        )
        context.user_data["stage"] = "registration_name"
        return ASK_NAME

    context.user_data.update({"name": user["name"], "city": user["city"], "stage": UserFlow.choosing_mode.name})
    remember_context(user_id, city=user["city"])
    await send_visual(
        context,
        chat_id,
        CATEGORY_MEDIA["hello"],
        f"Привет снова, {user['name']}! 😋\nЧто выбираем сегодня?",
        reply_markup=mode_keyboard(),
    )
    return CHOOSE_MODE


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Назови, пожалуйста, своё имя 😊")
        return ASK_NAME
    context.user_data["name"] = name
    context.user_data["stage"] = "registration_age"
    await update.message.reply_text("Супер! Сколько тебе лет?")
    return ASK_AGE


async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = normalize(update.message.text)
    if text.isdigit() and 0 < int(text) < 120:
        context.user_data["age"] = int(text)
        context.user_data["stage"] = "registration_city"
        await update.message.reply_text("Из какого ты города? 🏙️")
        return ASK_CITY
    await update.message.reply_text("Введи возраст цифрами 🙏")
    return ASK_AGE


async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip()
    if not city:
        await update.message.reply_text("Напиши, из какого ты города.")
        return ASK_CITY
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    city_canonical = canonicalize_city(city)
    upsert_user(
        chat_id,
        context.user_data.get("name", "друг"),
        context.user_data.get("age", 0),
        city_canonical,
    )
    context.user_data["city"] = city_canonical
    context.user_data["stage"] = UserFlow.choosing_mode.name
    remember_context(user_id, city=city_canonical)
    await send_visual(
        context,
        chat_id,
        CATEGORY_MEDIA["hello"],
        f"Отлично, {context.user_data['name']} из {city_canonical}! 🌆\nЧто будем искать?",
        reply_markup=mode_keyboard(),
    )
    return CHOOSE_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    norm_text = normalize(text)
    state = ensure_user_state(user_id)
    if norm_text == normalize(CONTROL_RANDOM):
        if is_processing_random(user_id):
            return ASK_QUERY
        mode_choice = state.get("mode") or context.user_data.get("mode") or "recipe"
        taste_choice = state.get("category") or context.user_data.get("taste")
        if not taste_choice:
            await send_text_safely(
                context,
                chat_id,
                "Сначала выбери категорию вкуса, а потом жми 🎲",
                reply_markup=taste_keyboard(),
            )
            return CHOOSE_TASTE
        context.user_data["mode"] = mode_choice
        if taste_choice:
            context.user_data["taste"] = taste_choice
        context.user_data["stage"] = UserFlow.waiting_for_input.name
        remember_context(user_id, mode=mode_choice, category=taste_choice, last_action="random")
        context.user_data.pop(SKIP_NEXT_MESSAGE, None)
        set_processing_random(user_id, True)
        reaction = reaction_message(taste_choice)
        await send_text_safely(context, chat_id, reaction, reply_markup=query_keyboard())
        await cozy_delay()
        if mode_choice == "restaurant":
            await send_random_place(update, context, taste_choice)
        else:
            await send_random_recipe(update, context, taste_choice)
        set_processing_random(user_id, False)
        return ASK_QUERY

    mode = resolve_mode(text)
    if not mode:
        await update.message.reply_text("Выбери кнопку: 🥣 рецепт или 🏙️ заведение.")
        return CHOOSE_MODE

    context.user_data["mode"] = mode
    existing_category = state.get("category") or context.user_data.get("taste")
    if existing_category:
        context.user_data["taste"] = existing_category
        context.user_data["stage"] = UserFlow.waiting_for_input.name
        remember_context(user_id, mode=mode, category=existing_category, last_action="mode")
        label = category_short_label(existing_category)
        prompt = (
            f"Продолжаю искать рецепты про {label}. Напиши идею или жми 🎲."
            if mode == "recipe"
            else f"Продолжаю искать места с акцентом на {label}. Напиши пожелание или жми 🎲."
        )
        await send_text_safely(context, chat_id, prompt, reply_markup=query_keyboard())
        return ASK_QUERY

    context.user_data["stage"] = UserFlow.choosing_category.name
    remember_context(user_id, mode=mode, last_action="mode")
    await send_visual(context, chat_id, CATEGORY_MEDIA["loading"], "🤔 Думаю, что тебе предложить…")
    await cozy_delay()
    prompt = "Что хочется сегодня приготовить?" if mode == "recipe" else "Что хочется сегодня попробовать?"
    await send_text_safely(context, chat_id, prompt, reply_markup=taste_keyboard())
    return CHOOSE_TASTE


async def recipe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    state = ensure_user_state(user_id)
    taste = context.user_data.get("taste") or state.get("category")
    context.user_data["mode"] = "recipe"
    context.user_data.pop(SKIP_NEXT_MESSAGE, None)
    remember_context(user_id, mode="recipe", category=taste, last_action="mode_command")
    if taste:
        context.user_data["stage"] = UserFlow.waiting_for_input.name
        label = category_short_label(taste)
        await send_text_safely(
            context,
            chat_id,
            f"Продолжаю искать рецепты про {label}. Напиши идею или жми 🎲.",
            reply_markup=query_keyboard(),
        )
        return ASK_QUERY
    context.user_data["stage"] = UserFlow.choosing_category.name
    await send_text_safely(
        context,
        chat_id,
        "Выбери вкус: сладкое, солёное, острое или полезное 👇",
        reply_markup=taste_keyboard(),
    )
    return CHOOSE_TASTE


async def place_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    state = ensure_user_state(user_id)
    taste = context.user_data.get("taste") or state.get("category")
    context.user_data["mode"] = "restaurant"
    context.user_data.pop(SKIP_NEXT_MESSAGE, None)
    remember_context(user_id, mode="restaurant", category=taste, last_action="mode_command")
    if taste:
        context.user_data["stage"] = UserFlow.waiting_for_input.name
        label = category_short_label(taste)
        await send_text_safely(
            context,
            chat_id,
            f"Продолжаю искать места с акцентом на {label}. Напиши пожелание или жми 🎲.",
            reply_markup=query_keyboard(),
        )
        return ASK_QUERY
    context.user_data["stage"] = UserFlow.choosing_category.name
    await send_text_safely(
        context,
        chat_id,
        "Давай выберем категорию вкуса 👇",
        reply_markup=taste_keyboard(),
    )
    return CHOOSE_TASTE


async def handle_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = normalize(update.message.text)
    user_id = update.effective_user.id if update.effective_user else update.effective_chat.id
    if text == normalize(CONTROL_BACK):
        stage = context.user_data.get("stage")
        if stage in (UserFlow.waiting_for_input.name, UserFlow.showing_result.name):
            context.user_data["stage"] = UserFlow.choosing_category.name
            context.user_data.pop(SKIP_NEXT_MESSAGE, None)
            set_processing_random(user_id, False)
            await update.message.reply_text("Окей, вернёмся к выбору вкуса 👇", reply_markup=taste_keyboard())
            return CHOOSE_TASTE
        context.user_data["stage"] = UserFlow.choosing_mode.name
        context.user_data.pop(SKIP_NEXT_MESSAGE, None)
        set_processing_random(user_id, False)
        await update.message.reply_text("Возвращаю в главное меню 🏠", reply_markup=mode_keyboard())
        return CHOOSE_MODE
    if text == normalize(CONTROL_CATEGORY_MENU):
        context.user_data["stage"] = UserFlow.choosing_category.name
        context.user_data.pop(SKIP_NEXT_MESSAGE, None)
        set_processing_random(user_id, False)
        set_processing_category(user_id, False)
        remember_context(user_id, last_action="category_menu")
        await update.message.reply_text("🧭 Вернёмся к выбору вкуса", reply_markup=taste_keyboard())
        return CHOOSE_TASTE
    if text == normalize(CONTROL_FINISH):
        name = context.user_data.get("name", "друг")
        await send_visual(
            context,
            update.effective_chat.id,
            CATEGORY_MEDIA["farewell"],
            f"Рад был помочь, {name}! 😋\nЧтобы начать заново, напиши /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
        reset_session(context)
        return ConversationHandler.END
    return None


async def handle_taste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ctrl = await handle_control(update, context)
    if ctrl is not None:
        return ctrl

    text = update.message.text or ""
    category = resolve_category(text)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    state = ensure_user_state(user_id)
    mode = context.user_data.get("mode") or state.get("mode") or "recipe"
    if is_processing_category(user_id):
        return CHOOSE_TASTE if category is None else ASK_QUERY
    if category is None:
        await update.message.reply_text("Выбери вкус из списка или нажми 🎲", reply_markup=taste_keyboard())
        return CHOOSE_TASTE

    set_processing_category(user_id, True)

    if category == "random":
        set_selected_category(context, None)
        fallback_category = state.get("category") or context.user_data.get("taste")
        if is_processing_random(user_id):
            set_processing_category(user_id, False)
            return ASK_QUERY
        if not fallback_category:
            set_processing_category(user_id, False)
            await update.message.reply_text("Сначала выбери вкус, а затем жми 🎲", reply_markup=taste_keyboard())
            return CHOOSE_TASTE
        set_processing_random(user_id, True)
        if fallback_category:
            context.user_data["taste"] = fallback_category
        context.user_data["stage"] = UserFlow.waiting_for_input.name
        context.user_data.pop(SKIP_NEXT_MESSAGE, None)
        reaction = reaction_message(fallback_category)
        remember_context(user_id, category=fallback_category, last_action="random")
        await send_text_safely(context, chat_id, reaction, reply_markup=query_keyboard())
        await cozy_delay()
        if mode == "recipe":
            await send_random_recipe(update, context, fallback_category)
        else:
            await send_random_place(update, context, fallback_category)
        set_processing_random(user_id, False)
        set_processing_category(user_id, False)
        return ASK_QUERY

    context.user_data["taste"] = category
    set_selected_category(context, category)
    context.user_data["stage"] = UserFlow.waiting_for_input.name
    remember_context(user_id, category=category, last_action="category_select")

    if mode == "recipe":
        prompt = "Отлично! Напиши, что ты примерно хочешь поесть, а я подберу лучший вариант 🍽 А если пока не решил — нажми на 🎲"
    else:
        prompt = "Что по настроению сегодня — японская кухня, грузинские хинкали или, может, что-то мексиканское с перчинкой? 🌮 Напиши, какая кухня тебя манит, и я подберу подходящие места рядом или жми 🎲"
    visual = CATEGORY_MEDIA.get(category)
    await send_visual(context, chat_id, visual, prompt, reply_markup=query_keyboard())
    set_processing_category(user_id, False)
    return ASK_QUERY


async def send_ai_suggestions(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    user_id: int,
    mode: str,
    category: Optional[str],
    query: Optional[str],
    city: Optional[str],
    preface: Optional[str] = None,
):
    if not ai_service.is_ai_available():
        return

    if preface:
        await send_text_safely(context, chat_id, preface, reply_markup=query_keyboard())
        await cozy_delay()

    taste_hint = taste_prompt_label(category)
    intent = mode if mode in ("recipe", "restaurant") else "neutral"
    if not category:
        intent = "neutral"

    prompt = ai_service.build_recommendation_prompt(
        city=city,
        category=category,
        mode=intent,
        query=query,
        taste_hint=taste_hint,
    )

    try:
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    except TelegramError:
        pass
    await cozy_delay()

    try:
        answer = await generate_ai_answer(prompt, user_id, query or prompt)
    except Exception as exc:
        log.warning("AI fallback error: %s", exc)
        await send_text_safely(context, chat_id, "⚠️ Не удалось получить ответ. Попробуем снова чуть позже.", reply_markup=query_keyboard())
        return

    formatted = prepare_ai_response(answer)
    paragraphs = [part.strip() for part in formatted.split("\n\n") if part.strip()] if formatted else []
    if paragraphs:
        paragraphs[0] = f"{pick_bridge_phrase()}\n{paragraphs[0]}"
    else:
        paragraphs = [pick_bridge_phrase()]
    payload = "\n\n".join(paragraphs)

    await send_text_safely(context, chat_id, payload, reply_markup=query_keyboard())
    remember_context(
        user_id,
        mode=mode,
        category=category,
        city=city,
        last_choice="ai_suggestion",
        last_action="ai_suggestion",
    )


async def handle_no_results(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    user_id: int,
    mode: str,
    category: Optional[str],
    query: Optional[str],
    city: Optional[str],
):
    await send_visual(
        context,
        chat_id,
        CATEGORY_MEDIA.get("not_found"),
        random.choice(FALLBACK_PREFACES),
        reply_markup=query_keyboard(),
    )
    await cozy_delay()
    await send_ai_suggestions(
        context,
        chat_id,
        user_id=user_id,
        mode=mode,
        category=category,
        query=query,
        city=city,
    )


async def send_recipe_card(context: ContextTypes.DEFAULT_TYPE, chat_id: int, recipe: dict):
    if not recipe:
        return
    category_label = recipe.get("category") or context.user_data.get("taste") or "unknown"
    print(f"[{category_label}] shown recipe: {recipe.get('title')}")
    intro = random.choice(RECIPE_INTROS)
    caption = (
        f"{intro}\n\n"
        f"🍽 {recipe['title']}\n"
        f"🧂 {recipe.get('ingredients', '')}\n"
        f"📝 {recipe.get('steps', '')}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍 Нравится", callback_data=f"recipe:like:{recipe['id']}"),
            InlineKeyboardButton("👎 Не нравится", callback_data=f"recipe:dislike:{recipe['id']}"),
            InlineKeyboardButton("🔁 Следующее", callback_data="recipe:next"),
        ]
    ])
    image_name = recipe.get("image") or CATEGORY_MEDIA.get(recipe.get("category") or context.user_data.get("taste"))
    await send_visual(context, chat_id, image_name, caption, reply_markup=kb)
    update_last_suggestion(context, "recipe", suggestion_id(recipe))


async def send_place_card(context: ContextTypes.DEFAULT_TYPE, chat_id: int, place: dict):
    if not place:
        return
    category_label = place.get("category") or context.user_data.get("taste") or "unknown"
    print(f"[{category_label}] shown place: {place.get('name')}")
    intro = random.choice(PLACE_INTROS)
    caption = (
        f"{intro}\n\n"
        f"🍴 {place['name']}\n📍 {place['address']} · ⭐️ {place.get('rating', '4.5')} · {place.get('cuisine', '')}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍 Нравится", callback_data=f"place:like:{place['id']}"),
            InlineKeyboardButton("👎 Не нравится", callback_data=f"place:dislike:{place['id']}"),
            InlineKeyboardButton("🔁 Следующее", callback_data="place:next"),
        ]
    ])
    image_name = place.get("image") or CATEGORY_MEDIA.get(place.get("category") or context.user_data.get("taste"))
    await send_visual(context, chat_id, image_name, caption, reply_markup=kb)
    update_last_suggestion(context, "place", suggestion_id(place))


async def send_random_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE, taste: Optional[str]):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    state = ensure_user_state(user_id)
    preferred_taste = taste or context.user_data.get("taste") or state.get("category")
    explicit_category = get_selected_category(context)
    with closing(get_conn()) as conn:
        recipe = fetch_random_recipe(conn, chat_id, preferred_taste, selected_category=explicit_category)
    if not recipe:
        context.user_data["stage"] = UserFlow.showing_result.name
        await handle_no_results(
            context,
            chat_id,
            user_id=user_id,
            mode="recipe",
            category=preferred_taste,
            query=None,
            city=context.user_data.get("city"),
        )
        set_processing_random(user_id, False)
        return
    last_recipe_id = get_last_suggestions(context).get("recipe")
    if suggestion_id(recipe) == last_recipe_id:
        for _ in range(3):
            with closing(get_conn()) as conn:
                alt = fetch_random_recipe(conn, chat_id, preferred_taste, selected_category=explicit_category)
            if not alt or suggestion_id(alt) != last_recipe_id:
                recipe = alt or recipe
                break
    category = recipe.get("category") or preferred_taste
    store_queue(context, "recipe", [recipe], {"kind": "random", "taste": category})
    context.user_data["taste"] = category
    context.user_data["stage"] = UserFlow.showing_result.name
    remember_context(
        user_id,
        mode=context.user_data.get("mode"),
        category=category,
        last_choice=recipe.get("title"),
        last_action="random_recipe",
    )
    try:
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    except TelegramError:
        pass
    await cozy_delay()
    await send_recipe_card(context, chat_id, recipe)
    set_processing_random(user_id, False)


async def send_random_place(update: Update, context: ContextTypes.DEFAULT_TYPE, taste: Optional[str]):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    state = ensure_user_state(user_id)
    city_state = state.get("city") or context.user_data.get("city")
    city = city_state or "Алматы"
    city_canonical = canonicalize_city(city)
    context.user_data["city"] = city_canonical
    remember_context(user_id, city=city_canonical)
    preferred_taste = taste or context.user_data.get("taste") or state.get("category")
    explicit_category = get_selected_category(context)
    with closing(get_conn()) as conn:
        place = fetch_random_place(conn, chat_id, city_canonical, preferred_taste, selected_category=explicit_category)
    if not place:
        context.user_data["stage"] = UserFlow.showing_result.name
        await handle_no_results(
            context,
            chat_id,
            user_id=user_id,
            mode="restaurant",
            category=preferred_taste,
            query=None,
            city=city_canonical,
        )
        set_processing_random(user_id, False)
        return
    last_place_id = get_last_suggestions(context).get("place")
    if suggestion_id(place) == last_place_id:
        for _ in range(3):
            with closing(get_conn()) as conn:
                alt = fetch_random_place(
                    conn,
                    chat_id,
                    city_canonical,
                    preferred_taste,
                    selected_category=explicit_category,
                )
            if not alt or suggestion_id(alt) != last_place_id:
                place = alt or place
                break
    category = place.get("category") or preferred_taste
    store_queue(context, "place", [place], {"kind": "random", "taste": category, "city": city_canonical})
    context.user_data["stage"] = UserFlow.showing_result.name
    context.user_data["taste"] = category
    remember_context(
        user_id,
        mode=context.user_data.get("mode"),
        category=category,
        last_choice=place.get("name"),
        last_action="random_place",
    )
    try:
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    except TelegramError:
        pass
    await cozy_delay()
    await send_place_card(context, chat_id, place)
    set_processing_random(user_id, False)


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ctrl = await handle_control(update, context)
    if ctrl is not None:
        return ctrl

    text = update.message.text or ""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else chat_id
    state = ensure_user_state(user_id)
    mode = context.user_data.get("mode") or state.get("mode") or "recipe"
    taste = context.user_data.get("taste") or state.get("category")
    explicit_category = get_selected_category(context)
    city = context.user_data.get("city") or state.get("city") or "Астана"
    context.user_data["city"] = city
    remember_context(user_id, city=city)
    city = ensure_user_state(user_id).get("city") or city
    context.user_data["city"] = city
    normalized_text = normalize(text)
    taste_button_map = {
        normalize("🍰 Сладкое"): "sweet",
        normalize("🍕 Солёное"): "salty",
        normalize("🌶 Острое"): "spicy",
        normalize("🥗 Полезное"): "healthy",
    }
    direct_category = taste_button_map.get(normalized_text)
    if direct_category and direct_category != "random":
        if is_processing_category(user_id):
            return ASK_QUERY
        set_processing_category(user_id, True)
        set_selected_category(context, direct_category)
        if direct_category != taste:
            context.user_data["taste"] = direct_category
            taste = direct_category
            remember_context(user_id, category=direct_category, last_action="category_shortcut")
            await send_text_safely(
                context,
                chat_id,
                f"🧠 Понял, хочется {taste_label(direct_category)}!",
                reply_markup=query_keyboard(),
            )
        context.user_data["stage"] = UserFlow.waiting_for_input.name
        prompt = (
            "Напиши блюдо или ключевое слово (например: «рамэн», «чизкейк», «суп») или жми 🎲"
            if mode == "recipe"
            else "Напиши, что хочется (например: «кофейня», «стейки», «суши») или жми 🎲"
        )
        visual = CATEGORY_MEDIA.get(direct_category)
        await send_visual(context, chat_id, visual, prompt, reply_markup=query_keyboard())
        set_processing_category(user_id, False)
        return ASK_QUERY

    context.user_data.pop(SKIP_NEXT_MESSAGE, None)

    inferred = detect_category_from_text(text)
    # Не переезжаем уже выбранную категорию кнопкой — только если ещё не было taste
    if inferred and inferred != "random" and not taste:
        taste = inferred
        context.user_data["taste"] = inferred
        set_selected_category(context, inferred)
        remember_context(user_id, category=inferred, last_action="category_inferred")
        await send_text_safely(
            context,
            chat_id,
            f"🧠 Понял, хочется {taste_label(inferred)}!",
            reply_markup=query_keyboard(),
        )

    resolved_category = resolve_category(text)
    if resolved_category == "random":
        if is_processing_random(user_id):
            return ASK_QUERY
        set_processing_random(user_id, True)
        context.user_data["stage"] = UserFlow.waiting_for_input.name
        remember_context(user_id, mode=mode, category=taste, last_action="random")
        context.user_data.pop(SKIP_NEXT_MESSAGE, None)
        reaction = reaction_message(taste)
        await send_text_safely(context, chat_id, reaction, reply_markup=query_keyboard())
        await cozy_delay()
        if mode == "recipe":
            await send_random_recipe(update, context, taste)
        else:
            await send_random_place(update, context, taste)
        set_processing_random(user_id, False)
        return ASK_QUERY

    if not text.strip():
        await send_text_safely(context, chat_id, "Напиши блюдо или настроение, я помогу найти 👇", reply_markup=query_keyboard())
        return ASK_QUERY

    context.user_data["stage"] = UserFlow.waiting_for_input.name
    remember_context(user_id, query=text.strip() or None, last_action="search")

    terms = expand_terms(text)
    primary_norm = normalize(text)
    await send_thinking(context, chat_id)

    with closing(get_conn()) as conn:
        if mode == "recipe":
            recipes = fetch_recipes(
                conn,
                terms,
                taste,
                limit=3,
                primary=primary_norm,
                selected_category=explicit_category,
            )
            if not recipes and taste and taste != "random":
                recipes = fetch_recipes(
                    conn,
                    [],
                    taste,
                    limit=3,
                    primary=primary_norm,
                    selected_category=explicit_category,
                )
            if not recipes:
                context.user_data["stage"] = UserFlow.showing_result.name
                await handle_no_results(
                    context,
                    chat_id,
                    user_id=user_id,
                    mode="recipe",
                    category=taste,
                    query=text,
                    city=city,
                )
                set_processing_category(user_id, False)
                return ASK_QUERY

            store_queue(
                context,
                "recipe",
                recipes,
                {"kind": "search", "terms": terms, "taste": taste, "primary": primary_norm},
            )
            last_recipe_id = get_last_suggestions(context).get("recipe")
            first_recipe = None
            for candidate in recipes:
                first_recipe = candidate
                if suggestion_id(candidate) != last_recipe_id:
                    break
            first_recipe = first_recipe or recipes[0]
            category_for_msg = first_recipe.get("category") or taste or detect_category_from_text(
                first_recipe.get("tags"), first_recipe.get("keywords")
            )
            context.user_data["taste"] = category_for_msg
            remember_context(
                user_id,
                mode=mode,
                category=category_for_msg,
                last_choice=first_recipe.get("title"),
                last_action="search_recipe",
            )
            context.user_data["stage"] = UserFlow.showing_result.name
            await send_text_safely(context, chat_id, pick_bridge_phrase(), reply_markup=query_keyboard())
            await cozy_delay()
            await send_recipe_card(context, chat_id, first_recipe)
        else:
            city_value = canonicalize_city(city or "Алматы") or "Алматы"
            places = fetch_restaurants(
                conn,
                city_value,
                terms,
                taste,
                limit=3,
                primary=primary_norm,
                selected_category=explicit_category,
            )
            if not places and taste and taste != "random":
                places = fetch_restaurants(
                    conn,
                    city_value,
                    [],
                    taste,
                    limit=3,
                    primary=primary_norm,
                    selected_category=explicit_category,
                )
            if not places:
                context.user_data["stage"] = UserFlow.showing_result.name
                await handle_no_results(
                    context,
                    chat_id,
                    user_id=user_id,
                    mode="restaurant",
                    category=taste,
                    query=text,
                    city=city_value,
                )
                set_processing_category(user_id, False)
                return ASK_QUERY

            store_queue(
                context,
                "place",
                places,
                {"kind": "search", "terms": terms, "taste": taste, "city": city_value, "primary": primary_norm},
            )
            last_place_id = get_last_suggestions(context).get("place")
            first_place = None
            for candidate in places:
                first_place = candidate
                if suggestion_id(candidate) != last_place_id:
                    break
            first_place = first_place or places[0]
            category_for_msg = first_place.get("category") or taste or detect_category_from_text(
                first_place.get("tags"), first_place.get("keywords")
            )
            context.user_data["taste"] = category_for_msg
            remember_context(
                user_id,
                mode=mode,
                category=category_for_msg,
                last_choice=first_place.get("name"),
                last_action="search_place",
            )
            context.user_data["stage"] = UserFlow.showing_result.name
            await send_text_safely(context, chat_id, pick_bridge_phrase(), reply_markup=query_keyboard())
            await cozy_delay()
            await send_place_card(context, chat_id, first_place)

    set_processing_category(user_id, False)
    return ASK_QUERY


async def next_item(context: ContextTypes.DEFAULT_TYPE, chat_id: int, item_type: str):
    advance_queue(context, item_type)
    current = current_item(context, item_type)
    if current:
        label = taste_label(queue_meta(context, item_type).get("taste"))
        skip_message = context.user_data.pop(SKIP_NEXT_MESSAGE, False)
        if item_type == "recipe":
            if not skip_message:
                await send_text_safely(
                    context,
                    chat_id,
                    f"Окей, подберу что-то ещё {label} 👇",
                    reply_markup=query_keyboard(),
                )
            await send_recipe_card(context, chat_id, current)
        else:
            if not skip_message:
                await send_text_safely(
                    context,
                    chat_id,
                    f"Есть ещё один вариант {label} 👇",
                    reply_markup=query_keyboard(),
                )
            await send_place_card(context, chat_id, current)
        return

    meta = queue_meta(context, item_type)
    context.user_data.pop(SKIP_NEXT_MESSAGE, None)
    kind = meta.get("kind")
    explicit_category = get_selected_category(context)
    with closing(get_conn()) as conn:
        if item_type == "recipe":
            if kind == "random":
                new_item = fetch_random_recipe(
                    conn,
                    chat_id,
                    meta.get("taste"),
                    selected_category=explicit_category,
                )
            else:
                new_item = fetch_recipes(
                    conn,
                    meta.get("terms", []),
                    meta.get("taste"),
                    limit=1,
                    primary=meta.get("primary"),
                    selected_category=explicit_category,
                )
                new_item = new_item[0] if new_item else None
        else:
            city = meta.get("city") or context.user_data.get("city", "Алматы")
            if kind == "random":
                new_item = fetch_random_place(
                    conn,
                    chat_id,
                    city,
                    meta.get("taste"),
                    selected_category=explicit_category,
                )
            else:
                new_items = fetch_restaurants(
                    conn,
                    city,
                    meta.get("terms", []),
                    meta.get("taste"),
                    limit=1,
                    primary=meta.get("primary"),
                    selected_category=explicit_category,
                )
                new_item = new_items[0] if new_items else None
    if not new_item:
        label = taste_label(meta.get("taste"))
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Больше {label} вариантов не нашёл 😅",
            reply_markup=query_keyboard(),
        )
        return
    last_id = get_last_suggestions(context).get("recipe" if item_type == "recipe" else "place")
    if suggestion_id(new_item) == last_id:
        with closing(get_conn()) as conn:
            if item_type == "recipe":
                alt = fetch_random_recipe(
                    conn,
                    chat_id,
                    meta.get("taste"),
                    selected_category=explicit_category,
                )
            else:
                alt = fetch_random_place(
                    conn,
                    chat_id,
                    meta.get("city") or context.user_data.get("city", "Алматы"),
                    meta.get("taste"),
                    selected_category=explicit_category,
                )
        if alt and suggestion_id(alt) != last_id:
            new_item = alt
    store_queue(context, item_type, [new_item], meta)
    if item_type == "recipe":
        await send_recipe_card(context, chat_id, new_item)
    else:
        await send_place_card(context, chat_id, new_item)


async def feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) < 2:
        await query.answer()
        return
    item_type, action, *rest = parts
    message = query.message
    chat_id = message.chat.id if message and message.chat else query.from_user.id
    item_id = int(rest[0]) if rest else None
    user_id = query.from_user.id
    answered = False

    with closing(get_conn()) as conn, conn:
        if item_type == "recipe":
            item = fetch_recipe_by_id(conn, item_id) if item_id else current_item(context, "recipe")
        else:
            item = fetch_restaurant_by_id(conn, item_id) if item_id else current_item(context, "place")
        current_item_id = suggestion_id(item)

        if not item:
            await query.answer("Нет данных, ищу другой вариант", show_alert=False)
            answered = True
            await query.edit_message_reply_markup(None)
            await context.bot.send_message(chat_id=chat_id, text="Не удалось найти этот вариант, попробуем другой 👇")
            await next_item(context, chat_id, item_type)
            return

        if action == "like":
            await query.answer("Сохранил 👍", show_alert=False)
            answered = True
            apply_feedback(conn, chat_id, item, item_type, True)
            log_item_feedback(user_id, current_item_id, item_type, "like", conn=conn)
            print(f"Feedback: {user_id} -> like")
            remember_context(user_id, last_action="feedback")
            await query.edit_message_reply_markup(None)
            await context.bot.send_message(chat_id=chat_id, text=random.choice(LIKE_REPLIES))
            await maybe_send_hint(context, chat_id)
            await next_item(context, chat_id, item_type)
            return
        if action == "dislike":
            await query.answer("Запомнил 👎", show_alert=False)
            answered = True
            apply_feedback(conn, chat_id, item, item_type, False)
            log_item_feedback(user_id, current_item_id, item_type, "dislike", conn=conn)
            print(f"Feedback: {user_id} -> dislike")
            remember_context(user_id, last_action="feedback")
            await query.edit_message_reply_markup(None)
            await context.bot.send_message(chat_id=chat_id, text="Окей, запомнил что не зашло 👎")
            await cozy_delay()
            await send_text_safely(context, chat_id, "Сейчас покажу другой вариант 👇", reply_markup=query_keyboard())
            await cozy_delay()
            context.user_data[SKIP_NEXT_MESSAGE] = True
            await next_item(context, chat_id, item_type)
            return
        if action == "next":
            await query.answer("Ищу дальше 🔁", show_alert=False)
            answered = True
            await query.edit_message_reply_markup(None)
            log_item_feedback(user_id, current_item_id, item_type, "next", conn=conn)
            print(f"Feedback: {user_id} -> next")
            remember_context(user_id, last_action="feedback")
            await next_item(context, chat_id, item_type)
            return

    if not answered:
        await query.answer()


async def favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT r.title
            FROM user_history h
            JOIN recipes r ON r.id = h.item_id
            WHERE h.chat_id=? AND h.item_type='recipe' AND h.liked=1
            ORDER BY h.created_at DESC
            LIMIT 15
            """,
            (chat_id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text("Пока ничего нет. ❤️ Добавляй понравившиеся блюда!")
        return
    titles = "\n".join(f"• {row['title']}" for row in rows)
    await update.message.reply_text(f"Твои любимые блюда 🍽:\n{titles}")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — начать заново\n"
        "/favorites — избранные блюда\n\n"
        "Пиши названия блюд или мест, или жми 🎲, если нужен сюрприз."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_session(context)
    await update.message.reply_text("До встречи! 👋🏻")
    return ConversationHandler.END


async def configure_commands(app: Application):
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Запустить диалог заново"),
                BotCommand("ask", "Спросить напрямую у ИИ"),
                BotCommand("recipe", "Подобрать рецепт"),
                BotCommand("place", "Найти заведение"),
                BotCommand("help", "Помощь"),
            ]
        )
    except TelegramError as exc:
        log.warning("Не удалось обновить команды бота: %s", exc)


def main():
    init_db()
    ensure_synonyms()
    request = HTTPXRequest(connect_timeout=25, read_timeout=60, write_timeout=60, pool_timeout=20)
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()
    app.post_init = configure_commands

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_city)],
            CHOOSE_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_mode)],
            CHOOSE_TASTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_taste)],
            ASK_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query)],
        },
        fallbacks=[
            CommandHandler("help", help_cmd),
            CommandHandler("favorites", favorites),
            CommandHandler("cancel", cancel),
            CommandHandler("recipe", recipe_cmd),
            CommandHandler("place", place_cmd),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("ask", ask_ai))
    app.add_handler(CommandHandler("recipe", recipe_cmd))
    app.add_handler(CommandHandler("place", place_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(feedback_handler, pattern="^(recipe|place):"))
    app.add_handler(CallbackQueryHandler(ai_feedback_callback, pattern="^ai_(like|dislike|next)\\|"))
    app.add_handler(CommandHandler("favorites", favorites))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
