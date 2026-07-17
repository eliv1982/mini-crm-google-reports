# Mini CRM Google Reports

Desktop mini-CRM с FastAPI backend, SQLite, Tkinter GUI и автоматическим экспортом аналитических отчетов в Google Sheets.

## Возможности

- управление клиентами: создание, просмотр, редактирование, удаление и архивирование;
- управление сделками: создание, просмотр, редактирование, удаление и привязка к клиенту;
- управление задачами: создание, просмотр, редактирование, удаление и связи с клиентами и сделками;
- связи между сущностями Clients -> Deals -> Tasks с nullable reference-полями;
- поиск по Clients, Deals и Tasks через HTTP API;
- Complete / Reopen для задач;
- генерация реалистичных тестовых данных через HTTP API backend;
- экспорт отчетов Clients / Deals / Tasks в Google Sheets;
- расчет аналитики по клиентам, сделкам и задачам;
- открытие созданного отчета и копирование его URL прямо из GUI.

## Архитектура

```text
Tkinter GUI
    |
    | HTTP
    v
FastAPI backend
    |
    v
SQLite

Tkinter / ReportExporter
    |
    +--> OAuth2 User -> Google Drive API -> Create Spreadsheet
    |
    +--> Service Account -> Google Sheets API -> Write / Format
```

CRM backend работает в Docker и отвечает только за HTTP API и SQLite-хранилище. Google OAuth2 и Google API используются на стороне локального desktop-приложения и CLI-скриптов, потому что именно там доступны пользовательский браузер, локальные credential-файлы и OAuth flow для Desktop App. Из-за этого backend container не получает Google credentials и не должен хранить их внутри себя.

## Структура проекта

```text
mini-crm-google-reports/
├── backend/
│   ├── repositories/
│   │   ├── clients.py
│   │   ├── deals.py
│   │   ├── errors.py
│   │   └── tasks.py
│   ├── routers/
│   │   ├── clients.py
│   │   ├── deals.py
│   │   └── tasks.py
│   ├── database.py
│   ├── main.py
│   └── schemas.py
├── credentials/
├── data/
├── google_integration/
│   ├── config.py
│   ├── google_drive.py
│   └── google_sheets.py
├── gui/
│   ├── api_client.py
│   ├── app.py
│   └── dialogs.py
├── reports/
│   ├── analytics.py
│   ├── api_client.py
│   └── exporter.py
├── scripts/
│   ├── export_reports.py
│   ├── fill_test_data.py
│   ├── smoke_test_backend.py
│   ├── smoke_test_google_drive.py
│   └── smoke_test_google_integration.py
├── tests/
│   ├── test_backend_api.py
│   ├── test_fill_test_data.py
│   ├── test_google_drive.py
│   ├── test_google_sheets.py
│   ├── test_gui_api_client.py
│   ├── test_gui_logic.py
│   ├── test_reports_analytics.py
│   ├── test_reports_exporter.py
│   └── ...
├── .dockerignore
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── README.md
├── requirements.txt
└── run_gui.py
```

## Технологии

- Python
- FastAPI
- sqlite3
- Pydantic
- Tkinter / ttk
- Docker / Docker Compose
- Google Drive API
- Google Sheets API
- OAuth2
- Google Service Account
- Faker
- pytest
- requests

## Модель данных

`Clients`
- хранят имя, компанию, email, телефон, статус и timestamps;
- статус ограничен значениями `active` и `archived`.

`Deals`
- хранят title, amount, status, expected_close_date и timestamps;
- `client_id` может быть `NULL`, поэтому сделка может существовать без привязки к клиенту;
- при удалении клиента связанный `client_id` переводится в `NULL` через `ON DELETE SET NULL`.

`Tasks`
- хранят title, description, due_date, completed и timestamps;
- `client_id` и `deal_id` являются nullable;
- задача может быть связана только с клиентом, только со сделкой, сразу с обеими сущностями или быть без связей;
- при удалении клиента или сделки соответствующие reference-поля переводятся в `NULL` через `ON DELETE SET NULL`.

## Подготовка Google Cloud

1. Включите Google Drive API в Google Cloud project.
2. Включите Google Sheets API в том же project.
3. Настройте OAuth consent screen / Google Auth Platform.
4. Создайте OAuth Desktop Client.
5. Добавьте свою учетную запись в `Test users`, если приложение работает в Testing mode.
6. Скачайте OAuth client JSON.
7. Создайте или используйте service account.
8. Скачайте service account JSON.
9. Создайте папку в Google Drive для отчетов.
10. Выдайте service account доступ `Editor` к этой папке.

README намеренно не содержит реальных email, folder IDs, client secrets или private keys.

## Credentials

Локальные пути:

- `credentials/client_secret.json`
- `credentials/service-account.json`
- `credentials/token.json`

`token.json` появляется после первой успешной OAuth-авторизации пользователя. Все credential-файлы, OAuth tokens и их варианты исключены из Git и не должны попадать в commit.

## Environment

Создайте локальный `.env` из шаблона:

```powershell
Copy-Item .env.example .env
```

Пример структуры `.env`:

```dotenv
DATABASE_PATH=data/crm.db
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
BACKEND_URL=http://localhost:8000

GOOGLE_OAUTH_CLIENT_SECRET_PATH=credentials/client_secret.json
GOOGLE_OAUTH_TOKEN_PATH=credentials/token.json
GOOGLE_SERVICE_ACCOUNT_PATH=credentials/service-account.json
GOOGLE_DRIVE_FOLDER_ID=your-google-drive-folder-id
```

Переменные окружения:

- `DATABASE_PATH`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `BACKEND_URL`
- `GOOGLE_OAUTH_CLIENT_SECRET_PATH`
- `GOOGLE_OAUTH_TOKEN_PATH`
- `GOOGLE_SERVICE_ACCOUNT_PATH`
- `GOOGLE_DRIVE_FOLDER_ID`

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

После установки создайте `.env` из `.env.example` и заполните только свои локальные значения.

## Запуск backend

```powershell
docker compose up -d --build
docker compose ps
```

Swagger:

- `http://localhost:8000/docs`

Health:

- `http://localhost:8000/health`

Остановка:

```powershell
docker compose down
```

SQLite persistence хранится в директории `./data`, поэтому база не теряется при перезапуске контейнера, пока каталог проекта сохраняется на диске.

## Запуск GUI

```powershell
python run_gui.py
```

Перед запуском GUI backend должен быть уже поднят и отвечать по `BACKEND_URL`.

## Генерация тестовых данных

Небольшой запуск:

```powershell
python -m scripts.fill_test_data --clients 5 --deals 5 --tasks 5 --seed 42
```

Полный учебный seed:

```powershell
python -m scripts.fill_test_data --clients 1000 --deals 1000 --tasks 1000 --seed 42
```

Генератор использует `requests`, `Faker` и HTTP API работающего backend. Прямая запись в SQLite не используется.

## Экспорт отчетов

CLI-команды:

```powershell
python -m scripts.export_reports --type clients
python -m scripts.export_reports --type deals
python -m scripts.export_reports --type tasks
python -m scripts.export_reports --type all
```

Что попадает в аналитику:

- `clients`: общее число клиентов, active / archived, наличие компании, самая частая компания, доля active;
- `deals`: общее число сделок, суммы, средние значения, распределение по статусам, won amount, сделки с клиентом и без клиента;
- `tasks`: общее число задач, completed / open, completion percentage, overdue open tasks, наличие связей client / deal.

Экспортер использует pagination и загружает все записи из CRM API, даже если основная таблица GUI показывает только первые 100 строк. Это же относится к reference data для selection в формах Add/Edit.

## Smoke tests

```powershell
python -m scripts.smoke_test_google_drive
python -m scripts.smoke_test_google_integration
python -m scripts.smoke_test_backend
```

- `smoke_test_google_drive`: проверяет OAuth-аутентификацию, создание Google Spreadsheet в Drive и чтение metadata, затем удаляет временный файл;
- `smoke_test_google_integration`: проверяет связку Drive create -> spreadsheet_id -> Sheets write/read/format и выполняет cleanup временного spreadsheet;
- `smoke_test_backend`: проверяет `/health`, CRUD-поток Client -> Deal -> Task, complete task и cleanup созданных CRM-сущностей.

## Tests

Основная команда:

```powershell
python -m pytest
```

На момент финальной приемки проекта: `104` теста успешно пройдены командой `python -m pytest`.

## Безопасность

- `.env` исключен из Git;
- credential-файлы и OAuth token-файлы исключены из Git;
- SQLite database-файлы исключены из Git;
- `credentials` исключена из Docker build context через `.dockerignore`;
- `.env`, token-файлы и database-файлы исключены из Docker build context;
- backend container не получает Google credentials;
- repository-слой использует parameterized SQL queries;
- пользовательские ошибки не должны печатать Google secrets.

## Ограничения MVP

- приложение ориентировано на локальное desktop-использование;
- в CRM нет пользовательской authentication / authorization;
- используется SQLite и sync backend;
- Docker configuration ориентирована на development и использует `uvicorn --reload`;
- основные таблицы GUI показывают максимум 100 записей;
- reference combobox получает полный список через pagination;
- production deployment configuration не подготовлена.

## Дальнейшее развитие

- PostgreSQL или Supabase вместо SQLite;
- web frontend вместо или вместе с Tkinter;
- пользовательская authentication / authorization;
- серверная pagination и sorting в UI;
- searchable combobox / autocomplete вместо загрузки полного reference list;
- background jobs для тяжелых экспортов;
- расписание автоматических отчетов;
- расширенная аналитика и dashboard;
- production Docker setup;
- persistent session / history / audit log при необходимости.
