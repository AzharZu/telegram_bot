# main.py — FindFood 3.0
import os, re, asyncio, logging
from contextlib import closing
from dotenv import load_dotenv

from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

from db import get_conn, init_db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN отсутствует в .env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("FindFood3")

ASK_NAME, ASK_CITY, CHOOSE_MODE, CHOOSE_TASTE, ASK_QUERY, CAROUSEL = range(6)

# ----------------- Утилиты -----------------
def normalize(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().lower())

def reaction_path(name: str) -> str:
    return os.path.join("images", name or "happy.png")

def user(conn, chat_id):
    return conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()

SYN = {
    "рамен": ["лапша", "суп", "азиатское"],
    "рамэн": ["лапша", "суп"],
    "пицца": ["сыр", "маргарита", "итальянская", "пиццерия"],
    "бургер": ["бургеры", "сэндвич", "мясо", "фастфуд"],
    "чизкейк": ["десерт", "сладкое", "торт"],
    "десерт": ["сладкое", "выпечка", "кофейня"],
    "сладкое": ["десерт", "выпечка", "кофе"],
    "солёное": ["основное", "ужин", "мясо", "бургер", "пицца"],
    "острое": ["чили", "тайская", "корейская", "мексиканская", "том ям", "рамен"],
    "салат": ["цезарь", "овощи", "зелень"],
    "суп": ["борщ", "том ям", "куриный", "лапша"]
}
def expand(q: str) -> list[str]:
    base = normalize(q)
    words = {base}
    for k, arr in SYN.items():
        if k in base:
            words.update(arr)
    # простая нормализация окончаний
    words.update([base.rstrip("ы"), base.rstrip("а"), base.rstrip("у"), base.rstrip("ой")])
    return [w for w in set(words) if w]

async def thinking(update: Update, kind: ChatAction, text: str):
    """Показать юзеру, что бот 'думает'."""
    await update.message.reply_chat_action(kind)
    await update.message.reply_text(text)
    await asyncio.sleep(0.6)  # лёгкая задержка — ощущение "ищет"

async def send_photo_or_text(update: Update, caption: str, img: str | None):
    p = reaction_path(img) if img else None
    if p and os.path.exists(p):
        with open(p, "rb") as f:
            await update.message.reply_photo(InputFile(f), caption=caption)
    else:
        await update.message.reply_text(caption)

# ----------------- /start + анкета -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    with closing(get_conn()) as conn:
        u = user(conn, update.effective_chat.id)
        if not u:
            await update.message.reply_text("👋 Я 🍴 FindFood. Как тебя зовут?")
            return ASK_NAME
        await update.message.reply_text(
            f"🙂 Привет снова, {u['name']} из {u['city']}! Что делаем?",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("🥣 Рецепт")], [KeyboardButton("🏙️ Заведение")]],
                resize_keyboard=True
            )
        )
        return CHOOSE_MODE

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Из какого ты города?")
    return ASK_CITY

async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip().capitalize()
    with closing(get_conn()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO users(chat_id,name,city) VALUES(?,?,?)",
                     (update.effective_chat.id, context.user_data["name"], city))
    await update.message.reply_text(
        "Класс! Что выберем?",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("🥣 Рецепт")], [KeyboardButton("🏙️ Заведение")]],
            resize_keyboard=True
        )
    )
    return CHOOSE_MODE

# ----------------- Шаг 1: режим -----------------
async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = normalize(update.message.text)
    if "рецепт" in t:
        context.user_data["mode"] = "recipe"
    elif "завед" in t:
        context.user_data["mode"] = "restaurant"
    else:
        await update.message.reply_text("Выбери: 🥣 Рецепт или 🏙️ Заведение")
        return CHOOSE_MODE

    await update.message.reply_text(
        "Какое настроение вкуса?",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("🍰 Сладкое"), KeyboardButton("🍔 Солёное"), KeyboardButton("🌶️ Острое")],
             [KeyboardButton("🎲 Удиви меня")]],
            resize_keyboard=True
        )
    )
    return CHOOSE_TASTE

# ----------------- Шаг 2: вкус -----------------
async def choose_taste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = normalize(update.message.text)
    if "слад" in t: context.user_data["taste"] = "sweet"
    elif "сол" in t: context.user_data["taste"] = "salty"
    elif "остр" in t: context.user_data["taste"] = "spicy"
    elif "удив" in t or "🎲" in t:
        context.user_data["taste"] = None
        return await start_carousel(update, context)
    else:
        await update.message.reply_text("Выбери один из вариантов 🙂")
        return CHOOSE_TASTE

    await update.message.reply_text(
        "Что именно хочешь? (например: пицца, бургер, чизкейк)\nИли нажми 🎲 Удиви меня",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🎲 Удиви меня")]], resize_keyboard=True)
    )
    return ASK_QUERY

# ----------------- Объединённый поиск -----------------
async def search_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = normalize(update.message.text)
    if "удив" in q or "🎲" in q:
        return await start_carousel(update, context)

    await thinking(update, ChatAction.TYPING, "⏳ Думаю, что тебе предложить…")

    mode = context.user_data.get("mode", "recipe")
    taste = context.user_data.get("taste", None)

    with closing(get_conn()) as conn:
        u = user(conn, update.effective_chat.id)
        name = u["name"] if u else "друг"
        city = u["city"] if u else "Алматы"

        words = expand(q)

        # Рецепты
        params_r, where_r = [], []
        for w in words:
            like = f"%{w}%"
            where_r.append("(title LIKE ? OR tags LIKE ? OR keywords LIKE ?)")
            params_r += [like, like, like]
        if taste:
            where_r.append("category LIKE ?")
            params_r.append(f"%{taste}%")
        sql_r = "SELECT * FROM recipes WHERE " + " OR ".join(where_r) + " ORDER BY likes DESC, RANDOM() LIMIT 3"
        recipes = conn.execute(sql_r, params_r).fetchall()

        # Заведения
        params_s = [f"%{city}%"]
        where_s = []
        for w in words:
            like = f"%{w}%"
            where_s.append("(name LIKE ? OR tags LIKE ? OR keywords LIKE ? OR cuisine LIKE ?)")
            params_s += [like, like, like, like]
        sql_s = "SELECT * FROM restaurants WHERE city LIKE ? AND (" + " OR ".join(where_s) + \
                ") ORDER BY rating DESC, RANDOM() LIMIT 3"
        restaurants = conn.execute(sql_s, params_s).fetchall()

        # Лог
        conn.execute("INSERT INTO logs(chat_id,user_query,bot_reply,meta) VALUES(?,?,?,?)",
                     (update.effective_chat.id, q, f"r={len(recipes)}, s={len(restaurants)}", taste or ""))

    # Формирование ответа под режим
    if mode == "recipe":
        if recipes:
            await update.message.reply_text(f"👨‍🍳 {name}, вот что нашёл по запросу «{q}»:")
            for r in recipes:
                caption = (f"🍽 {r['title']}\n\n"
                           f"🍳 {r['ingredients']}\n\n"
                           f"📝 {r['steps']}")
                await send_photo_or_text(update, caption, r["reaction"])
                await update.message.reply_text(
                    "Сохранить в избранное?",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❤️ В избранное", callback_data=f"fav_{r['id']}")]])
                )
            return CHOOSE_MODE
        else:
            await update.message.reply_text("Хмм… точного совпадения не вижу. Давай подберу варианты 🎲")
            return await start_carousel(update, context)
    else:
        if restaurants:
            await update.message.reply_text(f"🏙 Вот, куда можно сходить в {city}:")
            cards = []
            for res in restaurants:
                cards.append(f"• {res['name']} — {res['cuisine']} ({res['rating']}⭐️)\n  📍 {res['address']}")
            await update.message.reply_text("\n\n".join(cards))
            # подсказка: схожий рецепт
            if recipes:
                r = recipes[0]
                await send_photo_or_text(update, f"👨‍🍳 Похожее дома: {r['title']}", r["reaction"])
            return CHOOSE_MODE
        else:
            await update.message.reply_text("В твоём городе не нашёл подходящих мест. Зато есть классные блюда 🎲")
            return await start_carousel(update, context)

# ----------------- Карусель (3 блюда) -----------------
async def start_carousel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["carousel_i"] = 0
    context.user_data["liked"] = []
    await thinking(update, ChatAction.TYPING, "🤔 Перебираю рецепты…")
    return await send_next_in_carousel(update, context)

async def send_next_in_carousel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    taste = context.user_data.get("taste")
    with closing(get_conn()) as conn:
        if taste:
            row = conn.execute("SELECT * FROM recipes WHERE category LIKE ? ORDER BY RANDOM() LIMIT 1",
                               (f"%{taste}%",)).fetchone()
        else:
            row = conn.execute("SELECT * FROM recipes ORDER BY RANDOM() LIMIT 1").fetchone()
    if not row:
        await update.message.reply_text("Сегодня пусто 😅 Попробуй другой запрос.")
        return CHOOSE_MODE

    i = context.user_data.get("carousel_i", 0) + 1
    context.user_data["carousel_i"] = i
    caption = (f"🎲 Вариант #{i}\n\n"
               f"🍽 {row['title']}\n\n"
               f"🍳 {row['ingredients']}\n\n"
               f"📝 {row['steps']}")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❤️ Нравится", callback_data=f"like_{row['id']}"),
        InlineKeyboardButton("💔 Другое", callback_data="skip")
    ]])
    await update.message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
    await send_photo_or_text(update, caption, row["reaction"])
    # отдельным сообщением кнопки — чтобы фото не затирать подпись
    await update.message.reply_text("Оценишь?", reply_markup=kb)
    context.user_data["current_recipe"] = row["id"]
    return CAROUSEL

async def carousel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat_id

    with closing(get_conn()) as conn, conn:
        if data.startswith("like_"):
            rid = int(data.split("_")[1])
            conn.execute("INSERT OR IGNORE INTO favorites(chat_id, recipe_id) VALUES (?,?)", (chat_id, rid))
            conn.execute("UPDATE recipes SET likes = likes + 1 WHERE id=?", (rid,))
        conn.execute("INSERT INTO logs(chat_id,user_query,bot_reply,meta) VALUES (?,?,?,?)",
                     (chat_id, "carousel", data, ""))

    i = context.user_data.get("carousel_i", 0)
    if i >= 3:
        await q.edit_message_text("💫 Спасибо! Подборка готова. Возвращаюсь в меню.")
        return CHOOSE_MODE
    else:
        await q.edit_message_text("Ок! Подбираю следующий вариант…")
        # подсовываем следующее блюдо
        fake_update = Update(update.update_id, message=q.message)  # простая переиспользуемая обёртка
        return await send_next_in_carousel(fake_update, context)

# ----------------- Избранное -----------------
async def favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with closing(get_conn()) as conn:
        rows = conn.execute("""
            SELECT r.title FROM favorites f
            JOIN recipes r ON r.id=f.recipe_id
            WHERE f.chat_id=? ORDER BY f.created_at DESC LIMIT 15
        """, (update.effective_chat.id,)).fetchall()
    if not rows:
        await update.message.reply_text("Пока пусто. Жми ❤️ на понравившихся блюдах!")
    else:
        await update.message.reply_text("Твои избранные блюда:\n" + "\n".join(f"• {r['title']}" for r in rows))

async def fav_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rid = int(q.data.split("_")[1])
    with closing(get_conn()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO favorites(chat_id, recipe_id) VALUES (?,?)",
                     (q.message.chat_id, rid))
        conn.execute("UPDATE recipes SET likes = likes + 1 WHERE id=?", (rid,))
    await q.edit_message_reply_markup(None)
    await q.message.reply_text("Добавил в избранное ❤️")

# ----------------- Help -----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — начать заново\n"
        "/favorites — показать избранное\n\n"
        "Пиши, например: «бургер», «рамен», «десерт», «пицца маргарита».\n"
        "Или нажми «🎲 Удиви меня»."
    )

# ----------------- Main -----------------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_city)],
            CHOOSE_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_mode)],
            CHOOSE_TASTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_taste)],
            ASK_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_reply)],
            CAROUSEL: [CallbackQueryHandler(carousel_callback, pattern="^(like_|skip)$")],
        },
        fallbacks=[CommandHandler("help", help_cmd)],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(fav_button, pattern="^fav_"))
    app.add_handler(CommandHandler("favorites", favorites))
    app.add_handler(CommandHandler("help", help_cmd))

    app.run_polling()

if __name__ == "__main__":
    main()
