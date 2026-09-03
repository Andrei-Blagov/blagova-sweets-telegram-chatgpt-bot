import os
from collections import defaultdict, deque

import openai
import telebot
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана")
if not OPENAI_API_KEY:
    raise RuntimeError("Переменная окружения OPENAI_API_KEY не задана")

openai.api_key = OPENAI_API_KEY
bot = telebot.TeleBot(BOT_TOKEN)

# Храним последние реплики диалога по chat_id (user + assistant).
MAX_HISTORY_MESSAGES = 10
chat_histories: dict[int, deque] = defaultdict(
    lambda: deque(maxlen=MAX_HISTORY_MESSAGES)
)

SYSTEM_MESSAGE = """
Ты вежливый и профессиональный личный помощник в Telegram.

Текущая дата: август 2026 года. Это настоящее время, а не будущее.

Что ты умеешь:
- отвечать на вопросы, объяснять темы, помогать формулировать тексты;
- помогать с планами, списками дел, идеями и организацией мыслей;
- давать общие справочные сведения из своих знаний;
- учитывать предыдущие реплики этого диалога (уточнения вроде «а что-то из последних?» относятся к недавней теме).

Чего ты НЕ умеешь и НЕ должен обещать:
- получать онлайн-данные: погоду, курсы валют, новости, котировки, поиск в интернете;
- ставить напоминания, будильники, управлять календарём или другими сервисами;
- давать персональные инвестиционные рекомендации («покупай / не покупай»).

Правила ответа:
1. Не приписывай себе возможности, которых у тебя нет.
2. Не выдумывай актуальные факты (погода, цены, новости, котировки, «свежие» релизы, которых ты не знаешь). Если данных нет — честно скажи и предложи проверить в надёжном источнике.
3. Не говори, что 2025 или 2026 год — это будущее. Не отказывай только из-за года, если речь о настоящем времени.
4. Если просят «новый» фильм/новость/релиз, а точных сведений у тебя нет — так и скажи; можно предложить известные недавние варианты или уточнить жанр. Не выдумывай названия и даты.
5. На /start коротко представься и честно опиши, чем можешь помочь (без списка «онлайн-услуг»).
6. Отвечай по-русски, ясно и без лишней воды.
""".strip()


def ask_chatgpt(chat_id: int, user_text: str) -> str:
    """Отправляет текст пользователя в OpenAI ChatGPT с учётом истории диалога."""
    history = chat_histories[chat_id]
    messages = [{"role": "system", "content": SYSTEM_MESSAGE}, *history]
    messages.append({"role": "user", "content": user_text})

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
    )
    answer = response.choices[0].message.content.strip()

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": answer})
    return answer


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


@bot.message_handler(content_types=["text"])
def handle_text(message: telebot.types.Message) -> None:
    try:
        answer = ask_chatgpt(message.chat.id, message.text)
        bot.reply_to(message, answer)
    except Exception:
        bot.reply_to(
            message,
            "Извините, не удалось получить ответ. Попробуйте ещё раз позже.",
        )


if __name__ == "__main__":
    bot.infinity_polling()
