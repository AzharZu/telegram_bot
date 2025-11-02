"""AI helpers for FoodMateBot.

This module keeps Gemini configuration isolated and provides
utility helpers to build context-rich prompts for the bot.
"""

import asyncio
import logging
import re
from typing import Optional

import google.generativeai as genai


log = logging.getLogger("FindFoodAI")

_model: Optional[genai.GenerativeModel] = None


_MARKDOWN_PATTERN = re.compile(r"[*_`#>~]+")


def init_ai_service(api_key: Optional[str], model_name: str) -> None:
    """Configure Gemini model once at startup."""

    global _model
    if not api_key:
        log.warning("⚠️ GEMINI_API_KEY отсутствует. ИИ функции будут недоступны.")
        _model = None
        return

    try:
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(model_name)
        log.info("Gemini model '%s' готова к работе", model_name)
    except Exception as exc:  # pragma: no cover - defensive for API issues
        _model = None
        log.warning("Не удалось инициализировать Gemini (%s)", exc)


def is_ai_available() -> bool:
    return _model is not None


async def ask_ai(prompt: str) -> str:
    if not _model:
        raise RuntimeError("Gemini API не настроен.")

    loop = asyncio.get_running_loop()

    def _call_model() -> str:
        response = _model.generate_content(prompt)
        direct_text = getattr(response, "text", None)
        if direct_text:
            return direct_text.strip()

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", []) if content else []
            texts = [getattr(part, "text", "") for part in parts if getattr(part, "text", None)]
            combined = "\n".join(chunk.strip() for chunk in texts if chunk)
            if combined:
                return combined.strip()
        return ""

    raw_text = await loop.run_in_executor(None, _call_model)
    return clean_ai_text(raw_text)


def clean_ai_text(text: Optional[str]) -> str:
    if not text:
        return ""

    cleaned = _MARKDOWN_PATTERN.sub("", text)
    bullet_pattern = re.compile(r"^\s*(?:[-•*]|\d+[\.)])\s*")
    lines = []
    for line in cleaned.splitlines():
        stripped = bullet_pattern.sub("", line).rstrip()
        lines.append(stripped)
    compact = "\n".join(lines)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    compact = re.sub(r"\s+\n", "\n", compact)
    compact = re.sub(r"\.(\s*)(?=[А-ЯA-Z])", ".\n\n", compact)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact.strip()


CATEGORY_TITLES = {
    "sweet": "что-то сладкое",
    "salty": "что-то сытное",
    "spicy": "что-то острое",
    "healthy": "что-то полезное",
}

MODE_TITLES = {
    "recipe": "домашний рецепт",
    "restaurant": "заведение",
}


def build_recommendation_prompt(
    *,
    city: Optional[str],
    category: Optional[str],
    mode: str,
    query: Optional[str] = None,
    taste_hint: Optional[str] = None,
    persona: Optional[str] = None,
) -> str:
    """Compose a context-rich prompt for Gemini."""

    city_label = city or "Астаны"
    taste_label = taste_hint or CATEGORY_TITLES.get(category, "что-нибудь вкусное")
    context_line = ""
    if query:
        context_line = f" Пользователь упомянул запрос «{query}»."

    base_persona = persona or "Ты — дружелюбный бот FindFood"

    if mode == "recipe":
        return (
            f"{base_persona}. Пользователь из {city_label} ищет рецепт {taste_label}.{context_line}"
            " Ответь строго тремя абзацами без Markdown и маркеров:"
            "\n1) Первая строка — эмодзи и название блюда."
            "\n2) Вторая строка — короткий список ингредиентов через запятую."
            "\n3) Третья строка — 3–5 шагов приготовления в одном абзаце с номерами 1️⃣ 2️⃣ 3️⃣." 
            "\nНе добавляй лишних пояснений. Если запрос не про еду, мягко предложи выбрать блюдо, кафе или рецепт."
        )

    if mode == "restaurant":
        return (
            f"{base_persona}. Пользователь из {city_label} ищет место, где можно поесть {taste_label}.{context_line}"
            " Ответь строго тремя абзацами без Markdown и маркеров:"
            "\n1) Первая строка — название заведения и короткая атмосфера."
            "\n2) Вторая строка — блюдо или повод, ради которого стоит зайти."
            "\n3) Третья строка — совет по визиту или лучший момент для посещения." 
            "\nНе добавляй лишних рекомендаций. Если запрос не про еду, мягко предложи выбрать направление."
        )

    return (
        f"{base_persona}. Пользователь не знает, чего хочет, но находится в {city_label}.{context_line}"
        " Предложи один нейтральный вариант блюда или места. Ответь тремя абзацами:"
        "\n1) Первая строка — название с дружественным тоном."
        "\n2) Вторая строка — что это за вариант и из чего он состоит или чем привлекает."
        "\n3) Третья строка — короткий совет, как насладиться выбором." 
        "\nНе упоминай категорию и не используй Markdown. Если вопрос не про еду, вежливо направь к выбору блюда или места."
    )
