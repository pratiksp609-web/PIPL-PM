# PIPL AI Project Management System

A web application for PIPL to run engineering, manufacturing, procurement and turnkey projects from quotation to final payment. It covers clients, projects, quotations with revisions, client purchase orders checked against the approved quotation, client payments (receivable **X − Y = Z**), bills of materials with supplier purchase orders and payments, tasks with progress reminders, progress updates with revision history, a calendar, documents, notifications and status reports with optional AI analysis.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 |
| Database | PostgreSQL 14+ |
| Scheduler | APScheduler in the API process, guarded by a PostgreSQL advisory lock |
| Documents | pypdf, python-docx, mammoth + nh3 (sanitised previews), openpyxl, reportlab |
| AI (optional) | Anthropic API (`claude-opus-5-5` by default), server-side only |
| Frontend | React 19, TypeScript, Vite, TanStack Query, Recharts |

## Repository layout

```
backend/
  app/
    main.py            FastAPI app, middleware, error handling, serves frontend/dist
    config.py          Settings loaded from environment / backend/.env
    models.py          Database schema (SQLAlchemy)
    schemas.py         Request validation (Pydantic)
    security.py        Password hashing, session cookies, CSRF, rate limiting
    core.py            Permissions, pagination, audit log helpers
    finance.py         X − Y = Z receivables and procurement cost calculations
    storage.py         Upload validation, private file storage, text and field extraction
    reports.py         Status report builder (deterministic analysis)
    ai.py              Optional AI analysis with structured output
    scheduler.py       Reminders and alerts (progress, deadlines, expiries, payments, deliveries)
    notify.py          In-app notifications with de-duplication, optional email
    exports.py         PDF / Excel export
    cli.py             create-admin, seed-sample, reset-sample, run-checks
    routers/           One module per API area
  alembic/             Database migrations
  tests/               Automated tests (pytest, real PostgreSQL)
frontend/
  src/pages/           One page per sidebar item, plus project workspace and client profile
  src/components/      Shared UI, feature panels (commercial, payments, procurement, tasks, updates, reports)
```

## Setup

### 1. Database

```bash
sudo -u postgres psql -c "CREATE USER pipl WITH PASSWORD 'choose-a-password';"
sudo -u postgres psql -c "CREATE DATABASE pipl OWNER pipl;"
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then edit .env: DATABASE_URL, SECRET_KEY, ...
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli create-admin --email you@company.com --username admin --name "Your Name"
```

`create-admin` prompts for the password (or reads `ADMIN_PASSWORD`). Passwords need at least 8 characters with letters and numbers.

### 3. Frontend

```bash
cd frontend
npm ci
```

## Running

**Development** (two terminals; Vite proxies `/api` to the backend):

```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev            # http://localhost:5173
```

**Production-style** (single process; FastAPI serves the built frontend):

```bash
cd frontend && npm run build
cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Put it behind HTTPS (nginx, Caddy, a load balancer) and set `APP_ENV=production`, `COOKIE_SECURE=true` and a strong `SECRET_KEY`. The app refuses to start in production without them. Running several workers is safe: only one process runs the scheduled checks at a time thanks to the advisory lock.

## Configuration

All settings are environment variables, documented in [`backend/.env.example`](backend/.env.example). The important ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | Signs session tokens. Random, at least 32 characters in production |
| `COOKIE_SECURE` | `true` when served over HTTPS |
| `UPLOAD_DIR`, `MAX_UPLOAD_MB` | Private file storage location and size limit |
| `ANTHROPIC_API_KEY`, `AI_MODEL` | Optional AI analysis for status reports |
| `SMTP_HOST`, `SMTP_FROM`, `SMTP_*` | Optional email delivery of notifications |
| `SCHEDULER_ENABLED`, `SCHEDULER_INTERVAL_MINUTES` | Background reminders and alerts |
| `DEFAULT_TIMEZONE` | Default for users who have not set their own (Asia/Kolkata) |

### Enabling AI analysis

1. Create an API key in the Anthropic Console.
2. Set `ANTHROPIC_API_KEY=...` in `backend/.env` and restart the backend.
3. Settings → Integrations shows "Configured". New status reports then include an AI section that separates confirmed facts, estimates, risks, data issues and recommendations.

Without a key, or if the AI call fails, reports still generate with the deterministic template analysis, and the report says which one was used. The key is read only by the backend; it is never sent to the browser or written to logs.

### Enabling email

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` (and `SMTP_USE_TLS`). Users then choose "Also send notifications by email" under Settings → Reminders & notifications. Each notification shows whether its email was sent, failed (with the error) or not attempted. Without SMTP, notifications are in-app only.

### OCR for scanned documents

Text is read from PDF text layers, DOCX, XLSX and TXT files. For scanned images (PNG/JPG), install Tesseract (`apt install tesseract-ocr`) plus `pip install pytesseract pillow`; Settings → Integrations shows whether OCR is available.

## Sample data

```bash
cd backend
.venv/bin/python -m app.cli seed-sample    # creates clearly marked [SAMPLE] clients, projects, documents, users
.venv/bin/python -m app.cli reset-sample   # removes every [SAMPLE] record, sample user and sample file (run seed-sample again for fresh data)
```

Sample users log in with password `Sample@1234`: `sample.admin`, `sample.pm`, `sample.pm2`, `sample.engineer`, `sample.designer` (at `@sample.pipl.local`). Sample records are flagged `is_sample` and labelled in the UI. Both commands refuse to run when `APP_ENV=production` or `ALLOW_SAMPLE_DATA=false`, and reset only touches sample records.

## Tests

```bash
sudo -u postgres psql -c "CREATE DATABASE pipl_test OWNER pipl;"
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests run against a separate database (`TEST_DATABASE_URL`, default `pipl_test`), build the schema from the Alembic migrations, and wipe it between tests. They cover:

- **Access:** authentication, lockout, CSRF, session revocation, and role permissions, including unauthorized access to projects, finance and documents.
- **Projects and clients:** project creation and validation, and duplicate clients.
- **Documents:** uploads (bad type, content mismatch, missing file on disk), sanitised previews and field extraction.
- **Quotations and client POs:** quotation versioning and approval locking, and PO comparison with mandatory review of discrepancies.
- **Client payments:** X − Y = Z, partial payments, overpayment credit, duplicate and possible-duplicate payments, and supplier payments kept out of receivables.
- **Procurement:** BOM synchronisation and supplier PO limits.
- **Tasks and updates:** task rules and update revision history.
- **Calendar:** range limits.
- **Reminders and alerts:** reminder slots and de-duplication, and rule switches.
- **Reports:** report periods, the fallback when AI is not configured or fails, refusals, and exports.

The frontend is type-checked and linted with `npm run build` and `npm run lint`.

## How key rules work

- **Receivable (X − Y = Z)** is computed on the server in `finance.py`. X is the sum of verified client POs; if none, the approved quotation; if none, the project's manually entered contract value. Y counts only *verified* client payments. Z is never negative; any excess is shown separately as credit. Recorded-but-unverified, expected (pending), overdue, failed and reversed amounts are reported separately. Amounts in different currencies are never added together. Supplier payments live in their own tables and never enter this calculation.
- **Quotations** keep every revision. A new revision supersedes open drafts. Approved and superseded revisions are locked. Only one approved quotation exists per project. Approval requires a total, verified extraction and a consistent subtotal + tax = total.
- **Client POs** are compared field by field (values, currency, terms, delivery date, scope, line items) with the approved quotation. Verifying a PO with discrepancies requires explicit acknowledgement and review notes, and every decision is in the audit trail.
- **Reminders** run every `SCHEDULER_INTERVAL_MINUTES`. Progress reminders are sent at each user's interval (default 2 hours) only on their working days and hours, in their time zone, and only if they have open tasks. A unique key per user and time slot prevents duplicates across restarts and multiple workers.
- **Audit log** records who changed what, when, with before/after values, for all business records.

## Security notes

- Passwords: bcrypt hashed.
- Sessions: an httpOnly, SameSite=Lax cookie backed by a server-side session row, so logout and deactivation revoke it immediately.
- CSRF: a double-submit token is required for every state-changing request.
- Login: rate limiting, plus a temporary lockout after repeated failures.
- Permissions: checked in every API endpoint (Admin, Project Manager, Team Member), not only in the UI. Team Members see only projects they belong to or have tasks on, and never see financial data.
- Uploads: checked against an extension allowlist, file signature (magic bytes) and size limit. Files are stored under random names outside the web root and served only through authorised endpoints with `nosniff`. DOCX previews are sanitised, and previews are sandboxed with CSP.
- Exports: CSV and Excel cells are protected against formula injection.
- Errors and secrets: errors return a consistent JSON shape without stack traces. Logs are structured JSON with request IDs and contain no secrets.

## Known limitations

- Field extraction from quotations and POs is heuristic (labels and patterns, plus DOCX tables). Every extracted value is shown with a confidence level and must be verified by a person before approval. Unusual layouts will need manual entry.
- Scanned PDFs (images inside a PDF) are not OCR'd; only standalone image files are, when Tesseract is installed. Scanned PDFs can be previewed and their fields entered manually.
- Legacy `.doc` and `.xls` files can be stored and downloaded but not previewed or parsed. Convert them to `.docx`/`.xlsx` for previews.
- "Planned progress" is a linear estimate from start and expected completion dates, and is labelled as such. There is no baseline schedule or Gantt chart.
- Rate limiting is in memory per process. For multiple servers, put a shared limiter (e.g. at the reverse proxy) in front.
- Currency conversion is not performed; totals are shown per currency.
