import json
import os
import re
from collections import defaultdict, deque
from urllib.parse import quote

import requests
import telebot
from dotenv import load_dotenv
from openai import OpenAI
from telebot.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup

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
MEALDB_FILTER_INGREDIENT = (
    "https://www.themealdb.com/api/json/v1/1/filter.php?i={ingredient}"
)
BLAGOVA_CHAT_URL = "https://t.me/Nadejda1831"
MAX_RECIPE_CHOICES = 3
MAX_HISTORY_MESSAGES = 10
HTTP_TIMEOUT = 15

# TheMealDB понимает короткие английские названия блюд, без слова "recipe".
SEARCH_STOPWORDS = {
    "recipe",
    "recipes",
    "how",
    "to",
    "make",
    "cook",
    "cooking",
    "dish",
    "food",
    "meal",
    "with",
    "and",
    "for",
    "a",
    "an",
    "the",
    "fried",
    "boiled",
    "baked",
    "grilled",
    "roast",
    "roasted",
    "find",
    "search",
    "please",
    "рецепт",
    "рецепты",
    "как",
    "приготовить",
    "сделать",
    "нужен",
    "нужна",
    "нужно",
    "хочу",
}

# Частые русские запросы → рабочие ключи TheMealDB.
RU_DISH_ALIASES: dict[str, list[str]] = {
    "паста": ["pasta", "spaghetti", "carbonara", "penne"],
    "спагетти": ["spaghetti", "carbonara", "bolognese"],
    "карбонара": ["carbonara", "spaghetti"],
    "пицца": ["pizza"],
    "яичница": ["omelette", "egg"],
    "омлет": ["omelette", "egg"],
    "яйца": ["omelette", "egg"],
    "яйцо": ["omelette", "egg"],
    "блин": ["pancake", "blini"],
    "блины": ["pancake", "blini"],
    "оладьи": ["pancake"],
    "сырник": ["pancake", "cheesecake"],
    "сырники": ["pancake", "cheesecake"],
    "наполеон": ["cake", "apple cake"],
    "медовик": ["cake", "honey"],
    "торт": ["cake", "cheesecake"],
    "чизкейк": ["cheesecake", "cake"],
    "печенье": ["cookie", "biscuit"],
    "пряник": ["gingerbread", "cookie"],
    "пряники": ["gingerbread", "cookie"],
    "курица": ["chicken"],
    "куриц": ["chicken"],
    "рыба": ["fish", "salmon"],
    "лосось": ["salmon", "fish"],
    "суп": ["soup"],
    "борщ": ["soup", "beet"],
    "щи": ["soup"],
    "салат": ["salad"],
    "оливье": ["salad"],
    "стейк": ["steak", "beef"],
    "говядина": ["beef", "steak"],
    "свинина": ["pork"],
    "бургер": ["burger"],
    "рис": ["rice"],
    "лапша": ["noodle", "ramen"],
    "пельмен": ["dumpling"],
    "вареник": ["dumpling"],
    "шашлык": ["kebab", "pork"],
    "кебаб": ["kebab"],
    "плов": ["rice", "lamb"],
    "картошка": ["potato"],
    "картофель": ["potato"],
    "макарон": ["pasta", "spaghetti"],
    "лазанья": ["lasagna", "pasta"],
    "ризотто": ["risotto", "rice"],
    "суши": ["sushi", "salmon"],
    "вафли": ["waffle", "pancake"],
    "шоколад": ["chocolate", "cake"],
    "тирамису": ["cake", "dessert"],
    "брауни": ["brownie", "chocolate"],
    "кекс": ["cake", "muffin"],
    "маффин": ["muffin", "cake"],
    "круассан": ["croissant", "pastry"],
    "хачапури": ["bread", "cheese"],
    "шаурма": ["wrap", "chicken"],
    "сосиск": ["sausage"],
    "котлет": ["beef", "chicken"],
}

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
  (детальный заказ — через кнопку связи с менеджером BLAGOVA_SWEETS).

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
3. Не указывай в ответах Telegram-username менеджера (@...).
   Пиши «менеджер BLAGOVA_SWEETS» / «кнопка связи» — переход уже есть на кнопке.
4. На /start система шлёт готовое приветствие сама — не нужно его генерировать.
5. Отвечай по-русски, кратко и по делу.
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

recipe_query: 1-3 коротких английских названия блюда через запятую
  (только для recipe_search), БЕЗ слов recipe/how to cook.
  Если пользователь пишет по-русски — ОБЯЗАТЕЛЬНО переведи в английские названия.
  Примеры: «паста» → "pasta, spaghetti" | «яичница» → "omelette, egg"
  | «борщ» → "soup" | «пельмени» → "dumpling" | «шашлык» → "kebab".
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


def _clean_search_term(term: str) -> str:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", term.lower())
    kept = [w for w in words if w not in SEARCH_STOPWORDS]
    return " ".join(kept).strip()


def _alias_terms(text: str) -> list[str]:
    """Учитывает русские склонения: пасты/борща/сырников и т.п."""
    lowered = text.lower()
    words = re.findall(r"[а-яёa-z0-9]+", lowered)
    terms: list[str] = []
    for ru, aliases in RU_DISH_ALIASES.items():
        stem = ru[: max(4, len(ru) - 1)] if len(ru) >= 4 else ru
        matched = ru in lowered or any(
            len(w) >= 3 and (w.startswith(stem) or stem.startswith(w[: len(stem)]))
            for w in words
        )
        if matched:
            terms.extend(aliases)
    return terms


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


def translate_dish_terms_to_english(user_text: str) -> list[str]:
    """Переводит русский (и любой) запрос рецепта в английские ключи TheMealDB."""
    prompt = f"""
Пользователь ищет рецепт. Текст: {user_text}

Верни ТОЛЬКО JSON без markdown:
{{"terms":["term1","term2","term3"]}}

rules:
- terms: 2-4 коротких английских слова/фразы для поиска в TheMealDB;
- только латиница;
- без слов recipe, how, to, cook;
- русские блюда переводи в ближайшие международные названия
  (борщ→soup, пельмени→dumpling, шашлык→kebab, сырники→pancake,
   медовик→cake, оливье→salad, плов→rice).
""".strip()
    raw = _completion(
        [
            {
                "role": "system",
                "content": "Ты переводишь названия блюд в английские поисковые ключи.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=400,
    )
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
        terms = data.get("terms") or []
        result: list[str] = []
        for term in terms:
            cleaned = _clean_search_term(str(term))
            if cleaned and re.fullmatch(r"[A-Za-z0-9 ]+", cleaned):
                result.append(cleaned)
                first = cleaned.split()[0]
                if first not in SEARCH_STOPWORDS and first not in result:
                    result.append(first)
        return result[:6]
    except (json.JSONDecodeError, AttributeError, TypeError):
        return []


def build_search_terms(user_text: str, recipe_query: str) -> list[str]:
    """Собирает короткие английские ключи, которые реально находит TheMealDB."""
    candidates: list[str] = []

    # Сначала алиасы по русскому тексту — они самые надёжные.
    candidates.extend(_alias_terms(user_text))
    candidates.extend(_alias_terms(recipe_query or ""))

    for part in re.split(r"[,/;|]+", recipe_query or ""):
        cleaned = _clean_search_term(part)
        # В keys поиска допускаем только латиницу (TheMealDB не понимает кириллицу).
        if cleaned and re.fullmatch(r"[A-Za-z0-9 ]+", cleaned):
            candidates.append(cleaned)
            first = cleaned.split()[0]
            if first and first not in SEARCH_STOPWORDS:
                candidates.append(first)

    cleaned_user = _clean_search_term(user_text)
    if cleaned_user and re.fullmatch(r"[A-Za-z0-9 ]+", cleaned_user):
        candidates.append(cleaned_user)
        first = cleaned_user.split()[0]
        if first not in SEARCH_STOPWORDS:
            candidates.append(first)

    # Если английских ключей ещё нет — переводим русский запрос через модель.
    latin_ready = [
        c for c in candidates if re.fullmatch(r"[A-Za-z0-9 ]+", c.strip() or "")
    ]
    if not latin_ready and user_text.strip():
        candidates.extend(translate_dish_terms_to_english(user_text))

    seen: set[str] = set()
    result: list[str] = []
    for term in candidates:
        key = term.lower().strip()
        if (
            not key
            or key in seen
            or key in SEARCH_STOPWORDS
            or not re.fullmatch(r"[a-z0-9 ]+", key)
        ):
            continue
        seen.add(key)
        result.append(term.strip())
    return result[:8]


def _mealdb_search(term: str) -> list[dict]:
    response = requests.get(
        MEALDB_SEARCH.format(query=quote(term)),
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("meals") or []


def _mealdb_filter_ingredient(ingredient: str) -> list[dict]:
    response = requests.get(
        MEALDB_FILTER_INGREDIENT.format(ingredient=quote(ingredient)),
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("meals") or []


def search_recipes(
    user_text: str,
    recipe_query: str = "",
    limit: int = MAX_RECIPE_CHOICES,
) -> list[dict]:
    terms = build_search_terms(user_text, recipe_query)
    # Если после алиасов пусто — ещё одна попытка перевода.
    if not terms and user_text.strip():
        terms = translate_dish_terms_to_english(user_text)

    results: list[dict] = []
    seen_ids: set[str] = set()

    def add_meals(meals: list[dict]) -> None:
        for meal in meals:
            meal_id = str(meal.get("idMeal") or "")
            if not meal_id or meal_id in seen_ids:
                continue
            seen_ids.add(meal_id)
            results.append(
                {
                    "id": meal_id,
                    "title": meal.get("strMeal") or "Без названия",
                    "thumb": meal.get("strMealThumb") or "",
                }
            )
            if len(results) >= limit:
                return

    for term in terms:
        add_meals(_mealdb_search(term))
        if len(results) >= limit:
            return results

    # Запасной путь: фильтр по ингредиенту (egg, chicken, pasta…)
    for term in terms:
        token = term.split()[0]
        if len(token) < 3:
            continue
        add_meals(_mealdb_filter_ingredient(token))
        if len(results) >= limit:
            break

    return results[:limit]

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


def send_recipe_choices(
    chat_id: int,
    user_text: str,
    recipe_query: str = "",
    reply_to: int | None = None,
) -> None:
    recipes = search_recipes(user_text, recipe_query)
    if not recipes:
        bot.send_message(
            chat_id,
            "Не нашёл рецептов по этому запросу. Попробуйте другое название блюда "
            "(например: паста, омлет, курица, торт).",
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


def setup_bot_commands() -> None:
    """Меню Telegram: только рабочие команды."""
    bot.delete_my_commands()
    bot.set_my_commands(
        [
            BotCommand("start", "О боте и сброс диалога"),
            BotCommand("help", "Чем могу помочь"),
            BotCommand("recipe", "Пример: /recipe паста"),
        ]
    )


HELP_TEXT = (
    "Я помощник пекарни BLAGOVA_SWEETS.\n\n"
    "Могу:\n"
    "• найти рецепт — напишите «рецепт пасты» или /recipe паста;\n"
    "• подсказать по выпечке, тортам и пряникам;\n"
    "• связать с менеджером для заказа.\n\n"
    "Не ищу погоду, новости и прочие темы вне еды/пекарни."
)

START_TEXT = (
    "Привет! Я пекарня BLAGOVA_SWEETS. Моментально помогу с рецептами блюд и "
    "десертов (с фото до 3 вариантов), дам советы по выпечке и оформлению, "
    "придумаю идеи для праздничного стола. Заказы тортов и имбирных пряников — "
    "через кнопку связи с менеджером BLAGOVA_SWEETS."
)


@bot.message_handler(commands=["start"])
def handle_start(message: telebot.types.Message) -> None:
    chat_histories[message.chat.id].clear()
    bot.reply_to(message, START_TEXT, reply_markup=blagova_keyboard())
    chat_histories[message.chat.id].append({"role": "user", "content": "/start"})
    chat_histories[message.chat.id].append(
        {"role": "assistant", "content": START_TEXT}
    )
    send_promo_footer(message.chat.id)


@bot.message_handler(commands=["help"])
def handle_help(message: telebot.types.Message) -> None:
    bot.reply_to(message, HELP_TEXT, reply_markup=blagova_keyboard())
    send_promo_footer(message.chat.id)


@bot.message_handler(commands=["recipe"])
def handle_recipe_command(message: telebot.types.Message) -> None:
    query = message.text.split(maxsplit=1)
    dish = query[1].strip() if len(query) > 1 else ""
    if not dish:
        bot.reply_to(
            message,
            "Напишите блюдо после команды, например:\n/recipe паста",
        )
        send_promo_footer(message.chat.id)
        return
    send_recipe_choices(
        message.chat.id,
        dish,
        dish,
        reply_to=message.message_id,
    )


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
            send_recipe_choices(
                message.chat.id,
                user_text,
                classified["recipe_query"],
                reply_to=message.message_id,
            )
            chat_histories[message.chat.id].append(
                {"role": "user", "content": user_text}
            )
            chat_histories[message.chat.id].append(
                {
                    "role": "assistant",
                    "content": (
                        "Показаны варианты рецептов по запросу: "
                        f"{classified['recipe_query'] or user_text}"
                    ),
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
    setup_bot_commands()
    bot.infinity_polling()
