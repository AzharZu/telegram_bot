# main.py — FindFood 4.0
import asyncio
import os
import random
import re
import logging
from contextlib import closing
from typing import Iterable, Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db import get_conn, init_db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN отсутствует в .env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("FindFood4")

ASK_NAME, ASK_AGE, ASK_CITY, CHOOSE_MODE, CHOOSE_TASTE, ASK_QUERY = range(6)

CONTROL_BACK = "⬅️ Назад"
CONTROL_RESET = "🔁 Пройти заново"
CONTROL_FINISH = "👋🏻 Закончить"
CONTROL_RANDOM = "🎲 Не знаю, что хочу"

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
    "sweet": ("слад", "десерт", "конд", "sweet", "🍰"),
    "salty": ("сол", "сыт", "основ", "salty", "🍕", "бургер", "пицца"),
    "spicy": ("остр", "spicy", "азиат", "огонь", "🌶", "🔥", "том ям"),
    "healthy": ("полез", "здоров", "лёгк", "овощ", "healthy", "🥗", "фитнес"),
}

MODE_TOKENS = {
    "recipe": ("🥣", "рецепт", "готов", "блюд"),
    "restaurant": ("🏙", "завед", "место", "restaurant", "кафе"),
}

SYNONYMS = {
    "чизкейк": ["cheesecake", "десерт", "сладкое", "сырный торт"],
    "рамэн": ["рамен", "лапша", "суп", "азиатское", "спайси"],
    "рамен": ["рамэн", "лапша", "суп", "азиатское", "острое", "spicy"],
    "бургер": ["бургеры", "сэндвич", "мясо", "солёное"],
    "пицца": ["pizza", "маргарита", "итальянское", "солёное"],
    "салат": ["healthy", "овощи", "полезное"],
    "десерт": ["sweet", "торт", "выпечка"],
    "кофе": ["кофейня", "десерт", "sweet"],
    "суши": ["японская", "роллы", "азиатская", "рыба"],
    "тако": ["мексиканская", "острое", "spicy"],
    "овсянка": ["каша", "полезное", "здоровье"],
    "боул": ["healthy", "полезное", "лёгкое"],
}

DEFAULT_TASTES = ("sweet", "salty", "spicy", "healthy")


def normalize(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


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
    terms.update(base.split())
    terms.update({base.rstrip(suffix) for suffix in ("ы", "а", "ой", "ий", "я", "ь") if base.endswith(suffix)})
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


async def send_visual(context: ContextTypes.DEFAULT_TYPE, chat_id: int, image: Optional[str], text: Optional[str],
                      reply_markup=None):
    path = get_media_path(image)
    if path:
        with open(path, "rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=InputFile(photo, filename=os.path.basename(path)),
                caption=text,
                reply_markup=reply_markup,
            )
    elif text:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def send_thinking(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str = "🤔 Думаю..."):
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    await context.bot.send_message(chat_id=chat_id, text=text)
    await asyncio.sleep(0.4)


def reset_session(context: ContextTypes.DEFAULT_TYPE):
    preserved = context.user_data.get("hinted_categories", set())
    context.user_data.clear()
    if preserved:
        context.user_data["hinted_categories"] = preserved


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


def detect_category_from_text(*values: Optional[str]) -> str:
    text = " ".join(filter(None, values)).lower()
    for cat, tokens in TASTE_TOKENS.items():
        if any(token.replace(" ", "") in text.replace(" ", "") for token in tokens):
            return cat
    if "здоров" in text or "фитнес" in text or "healthy" in text:
        return "healthy"
    if "слад" in text or "dessert" in text:
        return "sweet"
    if "остр" in text or "spicy" in text or "азиат" in text:
        return "spicy"
    return "salty"


def taste_keyboard() -> ReplyKeyboardMarkup:
    keys = [
        [KeyboardButton("🍰 Сладкое"), KeyboardButton("🍕 Солёное")],
        [KeyboardButton("🌶 Острое"), KeyboardButton("🥗 Полезное")],
        [KeyboardButton(CONTROL_RANDOM)],
        [KeyboardButton(CONTROL_BACK), KeyboardButton(CONTROL_RESET)],
    ]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True, one_time_keyboard=False)


def mode_keyboard() -> ReplyKeyboardMarkup:
    keys = [
        [KeyboardButton("🥣 Хочу рецепт")],
        [KeyboardButton("🏙️ Хочу заведение")],
        [KeyboardButton(CONTROL_RESET)],
    ]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)


def query_keyboard() -> ReplyKeyboardMarkup:
    keys = [
        [KeyboardButton(CONTROL_RANDOM)],
        [KeyboardButton(CONTROL_BACK), KeyboardButton(CONTROL_RESET)],
        [KeyboardButton(CONTROL_FINISH)],
    ]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)


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
    return fallback if fallback and fallback != "random" else random.choice(DEFAULT_TASTES)


def fetch_recipes(conn, terms: list[str], taste: Optional[str], limit: int = 3):
    clauses = []
    params: list = []
    if terms:
        term_clauses = []
        for term in terms:
            like = f"%{term}%"
            term_clauses.append("(title LIKE ? OR tags LIKE ? OR keywords LIKE ?)")
            params.extend([like, like, like])
        clauses.append("(" + " OR ".join(term_clauses) + ")")
    if taste and taste != "random":
        clauses.append("category LIKE ?")
        params.append(f"%{taste}%")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT * FROM recipes {where} ORDER BY likes DESC, RANDOM() LIMIT ?"
    params.append(limit)
    return list(map(row_dict, conn.execute(sql, params).fetchall()))


def fetch_restaurants(conn, city: str, terms: list[str], taste: Optional[str], limit: int = 3):
    clauses = ["city LIKE ?"]
    params: list = [f"%{city}%"]
    if terms:
        term_clauses = []
        for term in terms:
            like = f"%{term}%"
            term_clauses.append("(name LIKE ? OR tags LIKE ? OR keywords LIKE ? OR cuisine LIKE ?)")
            params.extend([like, like, like, like])
        clauses.append("(" + " OR ".join(term_clauses) + ")")
    if taste and taste != "random":
        like = f"%{taste}%"
        clauses.append("(tags LIKE ? OR keywords LIKE ?)")
        params.extend([like, like])
    where = "WHERE " + " AND ".join(clauses)
    sql = f"SELECT * FROM restaurants {where} ORDER BY rating DESC, RANDOM() LIMIT ?"
    params.append(limit)
    return list(map(row_dict, conn.execute(sql, params).fetchall()))


def fetch_random_recipe(conn, chat_id: int, taste: Optional[str]) -> Optional[dict]:
    category = resolve_random_category(conn, chat_id, taste)
    params = []
    sql = "SELECT * FROM recipes"
    if category and category != "random":
        sql += " WHERE category LIKE ?"
        params.append(f"%{category}%")
    sql += " ORDER BY RANDOM() LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    data = row_dict(row)
    if data and not data.get("category"):
        data["category"] = category or detect_category_from_text(data.get("tags"), data.get("keywords"))
    return data


def fetch_random_place(conn, chat_id: int, city: str, taste: Optional[str]) -> Optional[dict]:
    category = resolve_random_category(conn, chat_id, taste)
    like_city = f"%{city}%"
    params = [like_city]
    sql = "SELECT * FROM restaurants WHERE city LIKE ?"
    if category and category != "random":
        tag = category
        sql += " AND (tags LIKE ? OR keywords LIKE ?)"
        params.extend([f"%{tag}%", f"%{tag}%"])
    sql += " ORDER BY rating DESC, RANDOM() LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    data = row_dict(row)
    if data and not data.get("category"):
        data["category"] = category or detect_category_from_text(data.get("tags"), data.get("keywords"))
    return data


def apply_feedback(conn, chat_id: int, item: dict, item_type: str, liked: bool):
    if not item:
        return
    category = item.get("category") or detect_category_from_text(item.get("category"), item.get("tags"), item.get("keywords"))
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
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🧠 Похоже, тебе нравится {label}!\nХочешь, подберу 3 новинки в этом вкусе?",
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    ensure_synonyms()
    chat_id = update.effective_chat.id
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

    context.user_data.update({"name": user["name"], "city": user["city"], "stage": "mode"})
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
    upsert_user(
        chat_id,
        context.user_data.get("name", "друг"),
        context.user_data.get("age", 0),
        city,
    )
    context.user_data["city"] = city
    context.user_data["stage"] = "mode"
    await send_visual(
        context,
        chat_id,
        CATEGORY_MEDIA["hello"],
        f"Отлично, {context.user_data['name']} из {city}! 🌆\nЧто будем искать?",
        reply_markup=mode_keyboard(),
    )
    return CHOOSE_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    chat_id = update.effective_chat.id
    norm = normalize(text)
    if norm == normalize(CONTROL_RESET):
        reset_session(context)
        return await start(update, context)

    mode = resolve_mode(text)
    if not mode:
        await update.message.reply_text("Выбери кнопку: 🥣 рецепт или 🏙️ заведение.")
        return CHOOSE_MODE

    context.user_data["mode"] = mode
    context.user_data["stage"] = "taste"
    await send_visual(context, chat_id, CATEGORY_MEDIA["loading"], "🤔 Думаю, что тебе предложить...")
    if mode == "recipe":
        await context.bot.send_message(chat_id=chat_id, text="Что хочется приготовить? 🍽", reply_markup=taste_keyboard())
    else:
        await context.bot.send_message(chat_id=chat_id, text="Какое место ищем? 🧭", reply_markup=taste_keyboard())
    return CHOOSE_TASTE


async def handle_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = normalize(update.message.text)
    if text == normalize(CONTROL_RESET):
        reset_session(context)
        return await start(update, context)
    if text == normalize(CONTROL_BACK):
        stage = context.user_data.get("stage")
        if stage in ("query", "random"):
            context.user_data["stage"] = "taste"
            await update.message.reply_text("Окей, вернёмся к выбору вкуса 👇", reply_markup=taste_keyboard())
            return CHOOSE_TASTE
        context.user_data["stage"] = "mode"
        await update.message.reply_text("Вернул на шаг выбора режима 😊", reply_markup=mode_keyboard())
        return CHOOSE_MODE
    if text == normalize(CONTROL_FINISH):
        name = context.user_data.get("name", "друг")
        await send_visual(
            context,
            update.effective_chat.id,
            CATEGORY_MEDIA["farewell"],
            f"Рад был помочь, {name}! 😋\nВозвращайся, когда проголодаешься.",
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
    if category is None:
        await update.message.reply_text("Выбери вкус из списка или нажми 🎲", reply_markup=taste_keyboard())
        return CHOOSE_TASTE

    context.user_data["taste"] = category
    context.user_data["stage"] = "query" if category != "random" else "random"

    if category == "random":
        mode = context.user_data.get("mode", "recipe")
        if mode == "recipe":
            await send_random_recipe(update, context, None)
        else:
            await send_random_place(update, context, None)
        return ASK_QUERY

    prompt = "Напиши блюдо или жми 🎲" if context.user_data.get("mode") == "recipe" else "Опиши заведение или жми 🎲"
    await update.message.reply_text(f"{prompt}", reply_markup=query_keyboard())
    return ASK_QUERY


async def send_recipe_card(context: ContextTypes.DEFAULT_TYPE, chat_id: int, recipe: dict):
    if not recipe:
        return
    cat = recipe.get("category") or detect_category_from_text(recipe.get("category"), recipe.get("tags"))
    media = recipe.get("reaction") or CATEGORY_MEDIA.get(cat or "sweet")
    caption = f"🍽 {recipe['title']}\n🧂 {recipe.get('ingredients', '')}. 📝 {recipe.get('steps', '')}"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❤️ Нравится", callback_data=f"recipe:like:{recipe['id']}"),
            InlineKeyboardButton("👎 Не нравится", callback_data=f"recipe:dislike:{recipe['id']}"),
            InlineKeyboardButton("🔁 Следующий", callback_data="recipe:next"),
        ]
    ])
    await send_visual(context, chat_id, media, caption, reply_markup=kb)


async def send_place_card(context: ContextTypes.DEFAULT_TYPE, chat_id: int, place: dict):
    if not place:
        return
    cat = place.get("category") or detect_category_from_text(place.get("tags"), place.get("keywords"))
    media = place.get("reaction") or CATEGORY_MEDIA.get(cat or "salty")
    caption = (
        f"🍴 {place['name']}\n📍 {place['address']} · ⭐️ {place.get('rating', '4.5')} · {place.get('cuisine', '')}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❤️ Нравится", callback_data=f"place:like:{place['id']}"),
            InlineKeyboardButton("👎 Не нравится", callback_data=f"place:dislike:{place['id']}"),
            InlineKeyboardButton("🔁 Другой", callback_data="place:next"),
        ]
    ])
    await send_visual(context, chat_id, media, caption, reply_markup=kb)


async def send_random_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE, taste: Optional[str]):
    chat_id = update.effective_chat.id
    with closing(get_conn()) as conn:
        recipe = fetch_random_recipe(conn, chat_id, taste or context.user_data.get("taste"))
    if not recipe:
        await send_visual(context, chat_id, CATEGORY_MEDIA["not_found"], "😅 Пока нет идей.\nХочешь попробовать ещё раз?")
        return
    store_queue(context, "recipe", [recipe], {"kind": "random", "taste": recipe.get("category")})
    await context.bot.send_message(chat_id=chat_id, text="🎲 Ладно, я выберу сам! Вот, что нашёл 👇")
    await send_recipe_card(context, chat_id, recipe)


async def send_random_place(update: Update, context: ContextTypes.DEFAULT_TYPE, taste: Optional[str]):
    chat_id = update.effective_chat.id
    city = context.user_data.get("city", "Алматы")
    with closing(get_conn()) as conn:
        place = fetch_random_place(conn, chat_id, city, taste or context.user_data.get("taste"))
    if not place:
        await send_visual(
            context,
            chat_id,
            CATEGORY_MEDIA["not_found"],
            "😅 В городе пока пусто.\nХочешь, покажу похожие блюда?",
        )
        return
    store_queue(context, "place", [place], {"kind": "random", "taste": place.get("category"), "city": city})
    await context.bot.send_message(chat_id=chat_id, text="🧠 Думаю, что тебе понравится 👇")
    await send_place_card(context, chat_id, place)


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ctrl = await handle_control(update, context)
    if ctrl is not None:
        return ctrl

    text = update.message.text or ""
    chat_id = update.effective_chat.id
    mode = context.user_data.get("mode", "recipe")
    taste = context.user_data.get("taste")

    if resolve_category(text) == "random":
        if mode == "recipe":
            await send_random_recipe(update, context, taste)
        else:
            await send_random_place(update, context, taste)
        return ASK_QUERY

    terms = expand_terms(text)
    await send_thinking(context, chat_id)

    with closing(get_conn()) as conn:
        if mode == "recipe":
            recipes = fetch_recipes(conn, terms, taste, limit=3)
            if not recipes and taste and taste != "random":
                recipes = fetch_recipes(conn, [], taste, limit=3)
            if not recipes:
                alt = fetch_random_recipe(conn, chat_id, taste)
                await send_visual(
                    context, chat_id, CATEGORY_MEDIA["not_found"],
                    f"😅 Не нашёл «{text}».\nХочешь похожее?"
                )
                if alt:
                    store_queue(context, "recipe", [alt], {"kind": "random", "taste": alt.get("category")})
                    await send_recipe_card(context, chat_id, alt)
                return ASK_QUERY
            store_queue(context, "recipe", recipes, {"kind": "search", "terms": terms, "taste": taste})
            await context.bot.send_message(chat_id=chat_id, text="🔎 Проверяю варианты по твоему вкусу...")
            await send_recipe_card(context, chat_id, recipes[0])
        else:
            city = context.user_data.get("city", "Алматы")
            places = fetch_restaurants(conn, city, terms, taste, limit=3)
            if not places and taste and taste != "random":
                places = fetch_restaurants(conn, city, [], taste, limit=3)
            if not places:
                alt = fetch_random_place(conn, chat_id, city, taste)
                await send_visual(
                    context,
                    chat_id,
                    CATEGORY_MEDIA["not_found"],
                    f"В {city} пока нет таких мест 😅\nПоказать похожие варианты?",
                )
                if alt:
                    store_queue(context, "place", [alt], {"kind": "random", "taste": alt.get("category"), "city": city})
                    await send_place_card(context, chat_id, alt)
                return ASK_QUERY
            store_queue(context, "place", places, {"kind": "search", "terms": terms, "taste": taste, "city": city})
            await context.bot.send_message(chat_id=chat_id, text="🔎 Проверяю варианты по твоему вкусу...")
            await send_place_card(context, chat_id, places[0])

    return ASK_QUERY


async def next_item(context: ContextTypes.DEFAULT_TYPE, chat_id: int, item_type: str):
    advance_queue(context, item_type)
    current = current_item(context, item_type)
    if current:
        if item_type == "recipe":
            await context.bot.send_message(chat_id=chat_id, text="Окей, попробуем что-то другое 👇")
            await send_recipe_card(context, chat_id, current)
        else:
            await context.bot.send_message(chat_id=chat_id, text="Посмотрим другой вариант 👇")
            await send_place_card(context, chat_id, current)
        return

    meta = queue_meta(context, item_type)
    kind = meta.get("kind")
    with closing(get_conn()) as conn:
        if item_type == "recipe":
            if kind == "random":
                new_item = fetch_random_recipe(conn, chat_id, meta.get("taste"))
            else:
                new_item = fetch_recipes(conn, meta.get("terms", []), meta.get("taste"), limit=1)
                new_item = new_item[0] if new_item else None
        else:
            city = meta.get("city") or context.user_data.get("city", "Алматы")
            if kind == "random":
                new_item = fetch_random_place(conn, chat_id, city, meta.get("taste"))
            else:
                new_items = fetch_restaurants(conn, city, meta.get("terms", []), meta.get("taste"), limit=1)
                new_item = new_items[0] if new_items else None
    if not new_item:
        await context.bot.send_message(chat_id=chat_id, text="Больше подходящих вариантов не нашёл 😅")
        return
    store_queue(context, item_type, [new_item], meta)
    if item_type == "recipe":
        await send_recipe_card(context, chat_id, new_item)
    else:
        await send_place_card(context, chat_id, new_item)


async def feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) < 2:
        return
    item_type, action, *rest = parts
    chat_id = query.message.chat_id
    item_id = int(rest[0]) if rest else None

    with closing(get_conn()) as conn, conn:
        if item_type == "recipe":
            item = fetch_recipe_by_id(conn, item_id) if item_id else current_item(context, "recipe")
        else:
            item = fetch_restaurant_by_id(conn, item_id) if item_id else current_item(context, "place")

        if action == "like":
            apply_feedback(conn, chat_id, item, item_type, True)
            await query.edit_message_reply_markup(None)
            await context.bot.send_message(chat_id=chat_id, text="❤️ Сохранил! Буду подбирать похожее.")
            await maybe_send_hint(context, chat_id)
            await next_item(context, chat_id, item_type)
            return
        if action == "dislike":
            apply_feedback(conn, chat_id, item, item_type, False)
            await query.edit_message_reply_markup(None)
            await context.bot.send_message(chat_id=chat_id, text="Окей, запомнил что не зашло 👎")
            await next_item(context, chat_id, item_type)
            return
        if action == "next":
            await query.edit_message_reply_markup(None)
            await next_item(context, chat_id, item_type)
            return


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


def main():
    init_db()
    ensure_synonyms()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

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
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(feedback_handler, pattern="^(recipe|place):"))
    app.add_handler(CommandHandler("favorites", favorites))
    app.add_handler(CommandHandler("help", help_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
