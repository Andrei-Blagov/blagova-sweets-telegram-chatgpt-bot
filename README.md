# telegram-chatgpt-bot

Telegram-бот пекарни **BLAGOVA_SWEETS**: поиск рецептов, советы по выпечке и связь с менеджером.

Репозиторий **приватный**. Образ публикуется на Docker Hub: [`andreiblagov/telegram-chatgpt-bot`](https://hub.docker.com/r/andreiblagov/telegram-chatgpt-bot).

## Возможности

- Поиск рецептов в интернете (TheMealDB) — до **3 кнопок** на выбор, затем описание и фото
- Советы по выпечке, тортам, пряникам, десертам и праздничному столу
- Кнопка связи с менеджером: [@Nadejda1831](https://t.me/Nadejda1831)
- После каждого ответа — промо-сообщение с кнопкой в BLAGOVA_SWEETS
- Вне тематики (погода, новости, «общий» чат и т.п.) — вежливый отказ и направление к пекарне

Модель: **`gpt-5-nano`** (самый дешёвый GPT-5).

## Требования

- Python 3.12+ (для локального запуска) или Docker
- Токен Telegram-бота (`BOT_TOKEN`)
- Ключ OpenAI API (`OPENAI_API_KEY`)

## Быстрый старт (локально)

```bash
cp .env.example .env
# заполните BOT_TOKEN и OPENAI_API_KEY в .env

pip install -r requirements.txt
python bot.py
```

## Docker

### Сборка и запуск

```bash
cp .env.example .env
# заполните .env

docker compose up -d --build
```

Сервисы:

| Сервис | Назначение |
|--------|------------|
| `bot` | Telegram-бот |
| `watchtower` | Раз в 60 сек проверяет Docker Hub и обновляет `bot` |

### Ручной push на Docker Hub

```powershell
.\scripts\build-and-push.ps1
```

## CI/CD (GitHub Actions)

При пуше в `main` workflow **Build and Push Docker Image** собирает образ и публикует его на Docker Hub.

Нужные secrets в репозитории (Settings → Secrets and variables → Actions):

| Secret | Значение |
|--------|----------|
| `DOCKERHUB_USERNAME` | `andreiblagov` |
| `DOCKERHUB_TOKEN` | Access Token Docker Hub (Read & Write) |

Ручной запуск:

```bash
gh workflow run "Build and Push Docker Image"
```

> Приватность репозитория на CI не влияет: Actions и secrets работают как обычно. Образ на Docker Hub остаётся доступен для pull на VPS.

## Деплой на VPS

1. Скопируйте `docker-compose.yml` и `.env` на сервер.
2. Запустите:

```bash
docker compose pull
docker compose up -d
```

Дальше цикл автоматический:

`git push` → GitHub Actions → Docker Hub → Watchtower на VPS обновляет контейнер.

## Переменные окружения

См. `.env.example`:

```
BOT_TOKEN=...
OPENAI_API_KEY=...
```

Файл `.env` в git **не** коммитится.

## Структура

```
.
├── bot.py                          # логика бота
├── Dockerfile
├── docker-compose.yml              # bot + watchtower
├── requirements.txt
├── .env.example
├── scripts/build-and-push.ps1      # локальный push образа
└── .github/workflows/docker-publish.yml
```

## Лицензия

Приватный проект. Все права сохранены.
