# Kvitto Payments API

Небольшой сервис оплаты курсов на FastAPI и PostgreSQL. Все денежные суммы в API и
базе хранятся целыми копейками. Интерактивная документация Swagger UI уже встроена
в FastAPI и доступна по адресу <http://localhost:8000/docs>.

## Структура проекта

```text
app/                 Код API
  main.py            HTTP-эндпоинты и проверка подписи вебхука
  database.py        Подключение к БД и сессии SQLAlchemy
  models.py          Таблицы тарифов и платежей
  schemas.py         Валидация запросов и модели ответов
  services.py        Расчёты и переходы статусов
alembic/             Миграции PostgreSQL
tests/               Тесты API
compose.yaml         PostgreSQL и запуск приложения
```

## Запуск через Docker Compose

Нужен запущенный Docker. Из корня проекта:

```bash
docker compose up --build
```

Compose запускает PostgreSQL, ждёт его готовности, применяет миграции Alembic и
запускает API. База сохраняется в томе `postgres_data`. API доступен на
<http://localhost:8000>, OpenAPI-схема — на <http://localhost:8000/openapi.json>.
Для локальной демонстрации используется секрет вебхука `dev-webhook-secret`; его
можно заменить переменной `WEBHOOK_SECRET` перед запуском Compose.

## Локальный запуск

Нужны Python 3.12+, `uv` и PostgreSQL. Можно поднять только базу из Compose:

```bash
docker compose up -d db
export DATABASE_URL='postgresql+psycopg://kvitto:kvitto@localhost:5433/kvitto'
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Если PostgreSQL установлен локально, создайте базу и установите `DATABASE_URL`
с её адресом. Для проверки подписи вебхука задайте `WEBHOOK_SECRET`; без этой
переменной проверка подписи отключена для локальной разработки.

## Тесты и качество кода

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
```

Тесты используют отдельную SQLite-базу в памяти и не изменяют рабочую PostgreSQL.
В CI дополнительно поднимается PostgreSQL и проверяется применение миграции.

## Примеры запросов

```bash
curl http://localhost:8000/tariffs

curl -X POST http://localhost:8000/payments \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: checkout-123' \
  -d '{"tariff_id":"standard","email":"student@example.com","method":"installment","installment_months":3,"promo_code":"kvitto10"}'

curl http://localhost:8000/payments/1

curl 'http://localhost:8000/payments?email=student@example.com&status=pending'
```

Для вебхука подпись — шестнадцатеричный HMAC-SHA256 от **точных байтов тела**.
Пример для секрета Compose:

```bash
BODY='{"payment_id":1,"status":"succeeded"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac 'dev-webhook-secret' -hex | awk '{print $2}')
curl -X POST http://localhost:8000/webhooks/bank \
  -H 'Content-Type: application/json' \
  -H "X-Signature: $SIG" \
  -d "$BODY"
```

## Правила API

- Тарифы: `basic` — 990000, `standard` — 1990000, `premium` — 2990000 копеек.
- Промокод `KVITTO10` уменьшает цену на 10%, регистр букв не важен.
- Рассрочка на 3, 6 или 12 платежей; остаток в копейках распределяется с начала графика.
- Повторный `POST /payments` с тем же `Idempotency-Key` возвращает исходный платёж
  с кодом 200, первое создание — с кодом 201.
- Статусы: `pending → succeeded/failed`, `succeeded → refunded`.
  Запрещённый переход возвращает 409 и `{"error":"invalid_transition"}`.
- Неизвестный платёж возвращает 404. Ошибки валидации возвращают 422.
- В `GET /payments` некорректный `email` возвращает 422; для корректного адреса
  без платежей ответ — 200 и пустой список `[]`. Регистр домена нормализуется.

Таблицы в рабочей базе создаются только миграциями. Для новой миграции после
изменения моделей используйте
`uv run --extra dev alembic revision --autogenerate -m "..."`, проверьте
полученный файл и примените `uv run --extra dev alembic upgrade head`.
