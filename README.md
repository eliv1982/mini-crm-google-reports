# Mini CRM Google Reports

An educational desktop mini-CRM built as a portfolio project. It manages clients, deals and tasks through a Tkinter GUI backed by a FastAPI service and a SQLite database, and it exports analytics reports to Google Sheets.

## Features

- Clients, deals and tasks with create, view, edit and delete; clients can also be archived and tasks can be completed or reopened.
- Nullable relations: a deal can reference a client, and a task can reference a client, a deal, both or neither.
- Search on all three entities through the HTTP API.
- Analytics reports (clients, deals, tasks) exported as new Google Spreadsheets, from the GUI or from a CLI.
- A demo-data generator that fills a running backend through its HTTP API.

## Architecture

```text
Tkinter GUI  ──HTTP──▶  FastAPI backend  ──▶  SQLite
     │
     └── reporting layer (analytics + exporter)
              ├── Google Drive API  (user OAuth)      creates the spreadsheet in a Drive folder
              └── Google Sheets API (service account) writes and formats the content
```

- **Backend** (`backend/`): FastAPI application with a SQLite database. It knows nothing about Google.
- **Desktop GUI** (`gui/`, `run_gui.py`): Tkinter/ttk client that talks to the backend over HTTP. The interface is in English.
- **Reporting** (`reports/`): fetches all records from the backend API (paginated), computes analytics, and writes the report.
- **Google integration** (`google_integration/`):
  - *Google Drive, user OAuth.* A Desktop-app OAuth client authorizes you in the browser once. The token is stored locally and is used to create a spreadsheet inside the configured Drive folder.
  - *Google Sheets, service account.* A service account writes and formats the created spreadsheet. It needs Editor access to that Drive folder.

Only the backend is containerized. The GUI, the report export and the Google credentials stay on the host machine, because they need a browser, a display and local credential files.

## Prerequisites

- **Python 3.12** is what the project is developed on and what the Docker image uses. The test suite also passes on Python 3.11 and 3.14 (see [Testing](#testing)). Other versions are untested.
- **Tkinter** for the desktop GUI. It ships with the Python installers for Windows and macOS. On Debian/Ubuntu install it separately (`sudo apt install python3-tk`); other Linux distributions have an equivalent package. Check with `python -m tkinter`. The backend, the CLI scripts and most tests do not need Tk.
- **Docker** (optional) to run the backend in a container.
- **A Google Cloud project** (only for report export); see [Google setup](#google-setup).

## Installation

Create a virtual environment and install the dependencies.

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux (use `python3` if `python` is not available):

```bash
python -m venv .venv
source .venv/bin/activate
```

Then, on any platform:

```bash
python -m pip install -r requirements.txt
```

Requirements files:

| File | Contents |
| --- | --- |
| `requirements.txt` | Everything needed to run the application locally: backend, GUI, reporting, Google integration. |
| `requirements-backend.txt` | Backend only. Installed by the Docker image and included by `requirements.txt`. |
| `requirements-dev.txt` | `requirements.txt` plus the test tooling and the demo-data generator (`Faker`). |

Versions are given as compatible ranges (a tested lower bound and a cap at the next major release). Transitive dependencies are not pinned.

## Configuration

Copy the template and edit the local copy:

```powershell
Copy-Item .env.example .env      # Windows (PowerShell)
```

```bash
cp .env.example .env             # macOS / Linux
```

Variables read by the code:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_PATH` | backend | SQLite file. Relative paths are resolved from the project root. Default: `data/crm.db`. |
| `BACKEND_URL` | GUI, reports, scripts | Where clients reach the backend. Default: `http://localhost:8000`. |
| `GOOGLE_OAUTH_CLIENT_SECRET_PATH` | Drive | OAuth Desktop client JSON downloaded from Google Cloud. |
| `GOOGLE_OAUTH_TOKEN_PATH` | Drive | Where the OAuth token is stored after the first authorization. |
| `GOOGLE_SERVICE_ACCOUNT_PATH` | Sheets | Service account key JSON. |
| `GOOGLE_DRIVE_FOLDER_ID` | reports | ID of the Drive folder that receives the reports. |

`.env.example` also lists `BACKEND_HOST` and `BACKEND_PORT`. The Python code does not read them; the backend port is set by the `uvicorn` command (`8000` in the Dockerfile and Compose file).

Real environment variables take precedence over values in `.env`.

## Google setup

Only needed for report export. The rest of the application works without it.

1. In a Google Cloud project, enable the **Google Drive API** and the **Google Sheets API**.
2. Configure the OAuth consent screen. While the app is in *Testing* mode, add your Google account as a test user.
3. Create an **OAuth client of type Desktop app** and download its JSON.
4. Create a **service account** and download its JSON key.
5. Create a Google Drive folder for the reports and share it with the service account's email address as **Editor**.
6. Put the two JSON files in `credentials/` (or point the environment variables elsewhere) and set `GOOGLE_DRIVE_FOLDER_ID` to the folder's ID (the last segment of the folder URL).

The default locations from `.env.example` are:

```text
credentials/client_secret.json    OAuth client        (you provide)
credentials/service-account.json  service account key (you provide)
credentials/token.json            OAuth token         (created automatically)
```

On the first export, a browser window opens for the Google authorization and the token is saved to `GOOGLE_OAUTH_TOKEN_PATH`. Later runs reuse it.

## Running the application

### 1. Backend

With Docker (development setup, see [Docker notes](#docker-notes)):

```bash
docker compose up -d --build
docker compose ps
```

Or directly with Python, from the project root:

```bash
python -m uvicorn backend.main:app --reload
```

Either way the API is at `http://localhost:8000`, with interactive docs at `/docs` and a health check at `/health`. Stop the container with `docker compose down`.

The SQLite database lives in `data/` and survives container restarts.

### 2. Demo data (optional)

The generator needs `Faker`, so install the development requirements first (`python -m pip install -r requirements-dev.txt`). The backend must be running; the script writes through its HTTP API.

```bash
python -m scripts.fill_test_data --clients 5 --deals 5 --tasks 5 --seed 42
```

Counts default to 1000 each. `--seed` (default 42) seeds the random generators; client e-mail addresses also contain a per-run identifier, so running the script twice adds distinct records. `--base-url` overrides `BACKEND_URL`.

### 3. Desktop GUI

```bash
python run_gui.py
```

The backend must already be running. Each tab (Clients, Deals, Tasks) has search, add, edit, delete and an **Export report** button. After an export, a dialog lets you open the spreadsheet or copy its URL. Tables show at most 100 records at a time; the related-record pickers in the Add/Edit forms load the full list.

### 4. Exporting reports from the command line

With the backend running and the Google setup done:

```bash
python -m scripts.export_reports --type clients
python -m scripts.export_reports --type deals
python -m scripts.export_reports --type tasks
python -m scripts.export_reports --type all      # default
```

Each report is a **new** Google Spreadsheet named `Mini CRM - <Clients|Deals|Tasks> Report - YYYY-MM-DD HH-MM` in the configured Drive folder. It has a summary block followed by a formatted table of all records:

- **Clients:** totals, active/archived counts, clients with and without a company, most common company, share of active clients.
- **Deals:** totals and amounts, averages, breakdown by status, won amount, deals with and without a client.
- **Tasks:** totals, completed and open counts, completion percentage, overdue open tasks, tasks with a client, with a deal, and without any link.

### Smoke tests (optional)

When run, these scripts call real services (the automated test suite only exercises them with fakes):

```bash
python -m scripts.smoke_test_backend             # needs the running backend
python -m scripts.smoke_test_google_drive        # needs Google OAuth setup
python -m scripts.smoke_test_google_integration  # needs OAuth + service account setup
```

The Google smoke tests create a temporary spreadsheet and delete it afterwards; the backend smoke test creates a client, deal and task and removes them.

## Testing

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

The suite uses fakes and temporary databases. It needs no running backend, no Google credentials and no network access to Google. Tests that import the Tkinter GUI are skipped automatically on a Python built without Tk; everything else still runs.

The suite was run successfully in fresh virtual environments on Python 3.11, 3.12 and 3.14 in September 2026.

## Docker notes

- Only the **backend** is containerized. `docker-compose.yml` defines a single `backend` service.
- The image installs `requirements-backend.txt` only: no test tooling, no Google libraries, no GUI dependencies.
- The setup is meant for development: the source (`./backend`) and the database directory (`./data`) are bind-mounted and `uvicorn` runs with `--reload`.
- `.dockerignore` keeps `.env`, `credentials/`, token files, databases, `tests/` and `gui/` out of the build context, and Compose mounts only `./backend` and `./data`. The container never receives Google credentials.
- The GUI and the report export run on the host and reach the container through `BACKEND_URL`.

## Security and credentials

- `credentials/*.json`, token files, `.env` and SQLite databases are listed in `.gitignore`. **Never commit them.** Keep OAuth client files, service account keys and tokens on your machine only.
- The Drive authorization requests the full `https://www.googleapis.com/auth/drive` scope; the Sheets client requests `https://www.googleapis.com/auth/spreadsheets`.
- Give the service account access only to the reports folder.
- Errors from the Google integration are designed not to echo credential contents or raw token-endpoint responses.

## Limitations

- Built for local, single-user desktop use. The API has **no authentication or authorization**; do not expose it to a network you do not trust.
- SQLite with a synchronous backend; no migrations.
- The Docker setup is for development (`--reload`, bind mounts), not a production deployment.
- Each export creates a new spreadsheet; nothing is updated or deleted. If writing fails after the spreadsheet was created, the file stays in the Drive folder and the error message reports its ID and link.
- Report export needs a Google Cloud project, a Drive folder and both credential types. The GUI tables show at most 100 records.
- `BACKEND_HOST` and `BACKEND_PORT` in `.env.example` are not used by the code (see [Configuration](#configuration)).

## Project structure

```text
mini-crm-google-reports/
├── backend/             FastAPI app, SQLite access, routers, repositories, schemas
├── gui/                 Tkinter desktop client (api_client, app, dialogs)
├── reports/             Analytics, backend API client for reports, Google Sheets exporter
├── google_integration/  Config loading, Drive client (OAuth), Sheets client (service account)
├── scripts/             Report export CLI, demo-data generator, smoke tests
├── tests/               Automated test suite
├── credentials/         Local credential files (gitignored, only .gitkeep is tracked)
├── data/                Local SQLite database (gitignored, only .gitkeep is tracked)
├── run_gui.py           GUI entry point
├── Dockerfile, docker-compose.yml, .dockerignore
├── requirements.txt, requirements-backend.txt, requirements-dev.txt
└── .env.example
```

## Data model

- **clients**: name, company, email, phone, status (`active` or `archived`), timestamps.
- **deals**: title, amount, status (`new`, `in_progress`, `won`, `lost`), expected close date, optional `client_id`, timestamps.
- **tasks**: title, description, due date, completed flag, optional `client_id` and `deal_id`, timestamps.

Deleting a client or deal sets the references that point to it to `NULL` (`ON DELETE SET NULL`); the dependent records are kept.

## Possible next steps

- Authentication for the API.
- PostgreSQL instead of SQLite, with migrations.
- Server-side pagination and sorting in the GUI.
- Scheduled or background report exports.
