import json
import os
import re
from collections import defaultdict, deque
from urllib.parse import quote

import requests
import telebot
from dotenv import load_dotenv
from openai import OpenAI
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана")
if not OPENAI_API_KEY:
    raise RuntimeError("Переменная окружения OPENAI_API_KEY не задана")

MODEL = "gpt-5-nano"
MEALDB_SEARCH = "https://www.themealdb.com/api/json/v1/1/search.php?s={query}"
MEALDB_LOOKUP = "https://www.themealdb.com/api/json/v1/1/lookup.php?i={meal_id}"
BLAGOVA_CHAT_URL = "https://t.me/Nadejda1831"
MAX_RECIPE_CHOICES = 3
MAX_HISTORY_MESSAGES = 10
HTTP_TIMEOUT = 15

client = OpenAI(api_key=OPENAI_API_KEY)
bot = telebot.TeleBot(BOT_TOKEN)

chat_histories: dict[int, deque] = defaultdict(
    lambda: deque(maxlen=MAX_HISTORY_MESSAGES)
)

SYSTEM_MESSAGE = """
Ты вежливый помощник пекарни BLAGOVA_SWEETS в Telegram.

Текущая дата: сентябрь 2026 года. Это настоящее время, а не будущее.

По каким вопросам к тебе обращаться:
- поиск рецептов блюд и десертов (система сама найдёт до 3 вариантов с фото);
- советы по выпечке, тортам, пряникам, десертам и домашней готовке;
- идеи для праздничного стола и угощений;
- краткие ответы про заказ тортов и имбирных пряников BLAGOVA_SWEETS
  (детальный заказ — через кнопку связи с менеджером @Nadejda1831).

По каким вопросам НЕ обращаться:
- общие темы «обо всём»: учёба, работа, тексты, планы, списки дел, финансы и т.п.;
- поиск в интернете чего угодно, кроме рецептов (погода, новости, курсы, товары);
- напоминания, календарь, будильники;
- инвестиционные советы.

Если вопрос не про еду, рецепты, выпечку или BLAGOVA_SWEETS —
вежливо скажи, чем именно можешь помочь, и предложи спросить рецепт
или написать в пекарню по кнопке ниже. Не отвечай как универсальный чат-бот.

Правила:
1. Не обещай возможностей, которых у тебя нет.
2. Не выдумывай факты. Если не знаешь — скажи прямо.
3. На /start коротко и ясно: кто ты, что умеешь (рецепты + выпечка + связь с пекарней),
   чего не умеешь. Без общих фраз вроде «помогу с любыми вопросами».
4. Отвечай по-русски, кратко и по делу.
""".strip()

CLASSIFY_PROMPT = """
Классифицируй сообщение пользователя. Верни ТОЛЬКО JSON без markdown:
{"intent":"chat"|"recipe_search"|"forbidden_search"|"off_topic","recipe_query":""}

intent:
- recipe_search — хочет рецепт, как приготовить блюдо/десерт, идеи блюд для готовки;
- forbidden_search — хочет поиск/данные из интернета НЕ про рецепты
  (погода, новости, курсы, товары, фильмы online, общий «найди в интернете» и т.п.);
- chat — вопрос про выпечку, торты, пряники, десерты, праздничный стол или BLAGOVA_SWEETS
  без запроса «найди рецепт»;
- off_topic — всё остальное (учёба, работа, тексты, планы, финансы, общие темы не про еду).

recipe_query: краткий поисковый запрос на английском для базы рецептов (только для recipe_search), иначе "".
""".strip()


def _completion(messages: list[dict], *, max_tokens: int = 2500) -> str:
    # gpt-5-nano тратит бюджет на reasoning; minimal + запас токенов
    # нужны, чтобы не получать пустой content.
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_completion_tokens=max_tokens,
        reasoning_effort="minimal",
    )
    content = response.choices[0].message.content
    return (content or "").strip()


def classify_message(user_text: str) -> dict:
    raw = _completion(
        [
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": user_text},
        ],
        max_tokens=400,
    )
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
        intent = data.get("intent", "chat")
        if intent not in {"chat", "recipe_search", "forbidden_search", "off_topic"}:
            intent = "chat"
        return {
            "intent": intent,
            "recipe_query": str(data.get("recipe_query") or "").strip(),
        }
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"intent": "chat", "recipe_query": ""}


def ask_chatgpt(chat_id: int, user_text: str) -> str:
    history = chat_histories[chat_id]
    messages = [{"role": "system", "content": SYSTEM_MESSAGE}, *history]
    messages.append({"role": "user", "content": user_text})
    answer = _completion(messages)
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": answer})
    return answer


def _meal_ingredients(meal: dict) -> list[str]:
    items: list[str] = []
    for i in range(1, 21):
        ingredient = (meal.get(f"strIngredient{i}") or "").strip()
        measure = (meal.get(f"strMeasure{i}") or "").strip()
        if not ingredient:
            continue
        items.append(f"{measure} {ingredient}".strip() if measure else ingredient)
    return items


def search_recipes(query: str, limit: int = MAX_RECIPE_CHOICES) -> list[dict]:
    query = query.strip()
    if not query:
        return []

    response = requests.get(
        MEALDB_SEARCH.format(query=quote(query)),
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    meals = response.json().get("meals") or []
    results: list[dict] = []
    for meal in meals[:limit]:
        results.append(
            {
                "id": meal["idMeal"],
                "title": meal.get("strMeal") or "Без названия",
                "thumb": meal.get("strMealThumb") or "",
            }
        )
    return results


def fetch_recipe(meal_id: str) -> dict | None:
    response = requests.get(
        MEALDB_LOOKUP.format(meal_id=quote(meal_id)),
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    meals = response.json().get("meals") or []
    if not meals:
        return None
    meal = meals[0]
    ingredients = _meal_ingredients(meal)
    instructions = (meal.get("strInstructions") or "").strip()
    return {
        "id": meal["idMeal"],
        "title": meal.get("strMeal") or "Без названия",
        "thumb": meal.get("strMealThumb") or "",
        "category": meal.get("strCategory") or "",
        "area": meal.get("strArea") or "",
        "ingredients": ingredients,
        "instructions": instructions,
        "source": meal.get("strSource") or meal.get("strYoutube") or "",
    }


def translate_recipe_to_ru(recipe: dict) -> str:
    ingredients = "\n".join(f"- {item}" for item in recipe["ingredients"])
    prompt = f"""
Переведи рецепт на русский ясно и кратко. Сохрани структуру.
Заголовок: {recipe['title']}
Категория: {recipe['category']}
Кухня: {recipe['area']}
Ингредиенты:
{ingredients}
Инструкция:
{recipe['instructions']}

Формат ответа:
Название
Категория / кухня (если есть)
Ингредиенты: список
Приготовление: нумерованные шаги
Без вступлений и пояснений от себя.
""".strip()
    return _completion(
        [
            {
                "role": "system",
                "content": "Ты переводишь кулинарные рецепты на русский язык.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=3000,
    )


PROMO_TEXT = "Вкуснейшие торты и имбирные пряники для вашего торжества!"


def blagova_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "Написать в BLAGOVA_SWEETS",
            url=BLAGOVA_CHAT_URL,
        )
    )
    return markup


def send_promo_footer(chat_id: int) -> None:
    """Промо-сообщение с кнопкой после каждого ответа бота."""
    bot.send_message(chat_id, PROMO_TEXT, reply_markup=blagova_keyboard())


def recipe_keyboard(recipes: list[dict]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for recipe in recipes[:MAX_RECIPE_CHOICES]:
        title = recipe["title"]
        if len(title) > 60:
            title = title[:57] + "..."
        markup.add(
            InlineKeyboardButton(
                title,
                callback_data=f"recipe:{recipe['id']}",
            )
        )
    return markup


def send_off_topic_reply(chat_id: int, reply_to: int | None = None) -> None:
    text = (
        "Я помощник пекарни BLAGOVA_SWEETS.\n\n"
        "Могу помочь с:\n"
        "• поиском рецептов (до 3 вариантов с фото);\n"
        "• советами по выпечке, тортам, пряникам и десертам;\n"
        "• заказом через менеджера пекарни.\n\n"
        "По другим темам не консультирую. Напишите, какой рецепт найти, "
        "или нажмите кнопку ниже."
    )
    bot.send_message(
        chat_id,
        text,
        reply_to_message_id=reply_to,
        reply_markup=blagova_keyboard(),
    )
    send_promo_footer(chat_id)


def send_forbidden_search_reply(chat_id: int, reply_to: int | None = None) -> None:
    text = (
        "Поиск в интернете доступен только для рецептов.\n\n"
        "Для тортов и имбирных пряников советую лучшую пекарню "
        "BLAGOVA_SWEETS — там помогут с заказом и выбором."
    )
    bot.send_message(
        chat_id,
        text,
        reply_to_message_id=reply_to,
        reply_markup=blagova_keyboard(),
    )
    send_promo_footer(chat_id)


def send_recipe_choices(chat_id: int, query: str, reply_to: int | None = None) -> None:
    recipes = search_recipes(query)
    if not recipes:
        bot.send_message(
            chat_id,
            "Не нашёл рецептов по этому запросу. Попробуйте другое название блюда.",
            reply_to_message_id=reply_to,
        )
        send_promo_footer(chat_id)
        return

    lines = ["Нашёл варианты рецептов — выберите один:"]
    for i, recipe in enumerate(recipes, start=1):
        lines.append(f"{i}. {recipe['title']}")

    bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_to_message_id=reply_to,
        reply_markup=recipe_keyboard(recipes),
    )
    send_promo_footer(chat_id)


@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message) -> None:
    chat_histories[message.chat.id].clear()
    try:
        answer = ask_chatgpt(message.chat.id, "/start")
        bot.reply_to(message, answer)
    except Exception:
        bot.reply_to(
            message,
            "Извините, не удалось получить ответ. Попробуйте ещё раз позже.",
        )
    send_promo_footer(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("recipe:"))
def handle_recipe_callback(call: telebot.types.CallbackQuery) -> None:
    meal_id = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id, "Открываю рецепт...")
    chat_id = call.message.chat.id
    try:
        recipe = fetch_recipe(meal_id)
        if not recipe:
            bot.send_message(chat_id, "Рецепт не найден.")
            send_promo_footer(chat_id)
            return

        text = translate_recipe_to_ru(recipe)
        if len(text) > 3500:
            text = text[:3490] + "…"

        if recipe["thumb"]:
            caption = text if len(text) <= 1024 else text[:1000] + "…"
            bot.send_photo(
                chat_id,
                recipe["thumb"],
                caption=caption,
            )
            if len(text) > 1024:
                bot.send_message(chat_id, text)
        else:
            bot.send_message(chat_id, text)
    except Exception:
        bot.send_message(
            chat_id,
            "Не удалось загрузить рецепт. Попробуйте ещё раз.",
        )
    send_promo_footer(chat_id)


@bot.message_handler(content_types=["text"])
def handle_text(message: telebot.types.Message) -> None:
    user_text = message.text or ""
    try:
        classified = classify_message(user_text)
        intent = classified["intent"]

        if intent == "forbidden_search":
            send_forbidden_search_reply(message.chat.id, message.message_id)
            chat_histories[message.chat.id].append(
                {"role": "user", "content": user_text}
            )
            chat_histories[message.chat.id].append(
                {
                    "role": "assistant",
                    "content": (
                        "Поиск в интернете только для рецептов. "
                        "Рекомендация: пекарня BLAGOVA_SWEETS."
                    ),
                }
            )
            return

        if intent == "off_topic":
            send_off_topic_reply(message.chat.id, message.message_id)
            chat_histories[message.chat.id].append(
                {"role": "user", "content": user_text}
            )
            chat_histories[message.chat.id].append(
                {
                    "role": "assistant",
                    "content": (
                        "Помогаю только с рецептами, выпечкой и заказами "
                        "BLAGOVA_SWEETS."
                    ),
                }
            )
            return

        if intent == "recipe_search":
            query = classified["recipe_query"] or user_text
            send_recipe_choices(message.chat.id, query, message.message_id)
            chat_histories[message.chat.id].append(
                {"role": "user", "content": user_text}
            )
            chat_histories[message.chat.id].append(
                {
                    "role": "assistant",
                    "content": f"Показаны варианты рецептов по запросу: {query}",
                }
            )
            return

        answer = ask_chatgpt(message.chat.id, user_text)
        bot.reply_to(message, answer)
        send_promo_footer(message.chat.id)
    except Exception:
        bot.reply_to(
            message,
            "Извините, не удалось получить ответ. Попробуйте ещё раз позже.",
        )
        send_promo_footer(message.chat.id)


if __name__ == "__main__":
    bot.infinity_polling()
