# Calendar Audit Tool

A Django application that connects to a user's primary Google Calendar,
synchronizes recent events into PostgreSQL, and presents a dashboard of meeting
habits and time allocation.

The primary data-refresh path is a Google Calendar push webhook. After OAuth,
the application bootstraps itself: a background thread runs the initial full sync
and registers the push channel automatically. Users can also trigger an on-demand
sync from either dashboard when a notification is missed or delayed. There is no
periodic scheduler.

## Features

- **Multi-user support**: each Google account gets its own isolated data.
- Sign in with Google — no separate account creation needed.
- Automatic initial sync and push-channel registration after sign-in.
- Real-time calendar updates through Google push notifications.
- Manual sync button as a backup on both dashboards.
- Preview events for the next seven days.
- Store calendar data in Supabase or local PostgreSQL.
- Review meeting audit metrics from the Audit Dashboard.

## Technology

- Python 3.14
- Django 6.1
- Django REST Framework
- PostgreSQL through Psycopg 3
- Supabase PostgreSQL or a local PostgreSQL server
- Google Calendar API

## Project layout

```text
config/
  database.py            DATABASE_URL, SSL, and pooler configuration
  settings.py            Django and Google integration settings
  api_urls.py            API route composition

googlecal/
  client.py              Credential loading and Google API client
  oauth.py               OAuth authorization-code flow
  views.py               Main dashboard and OAuth callbacks
  templates/             Connected-calendar dashboard

calsync/
  bootstrap.py           Post-OAuth bootstrap: full sync + watch channel
  models.py              Events, sync state, and watch channels
  sync.py                Full and incremental synchronization
  watch.py               Google push-channel management
  views.py               Manual sync and webhook endpoints
  management/commands/
    check_database.py    Database health and connection check
    dev_watch.py         Register a local ngrok webhook channel (DEBUG only)

calaudit/
  queries.py             Calendar analytics queries
  views.py               Audit API views and dashboard
  templates/             Audit dashboard

scripts/
  quickstart.py          Standalone Google API smoke test
```

## Prerequisites

- Python 3.14
- A Google Cloud project with the Google Calendar API enabled
- A Supabase project or local PostgreSQL database
- ngrok (for real-time webhooks during local development)

## Installation

Create the virtual environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

## Environment configuration

All secrets belong in `.env`, which is gitignored. Do not add credentials to
`.env.example`.

### Supabase database

In the Supabase dashboard, open the project's **Connect** panel and copy the
Session pooler connection URI. Session mode uses port `5432` and is appropriate
for this persistent Django application, including from IPv4-only networks.

```dotenv
DATABASE_URL=postgresql://postgres.PROJECT_REF:ENCODED_PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require
DB_CONN_MAX_AGE=60
```

Percent-encode reserved characters in the password before placing it in the
URL. A transaction-pooler URI on port `6543` is also supported.

When `DATABASE_URL` is absent, the application uses these local PostgreSQL
settings instead:

```dotenv
POSTGRES_DB=calendar_audit
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### Google OAuth (Sign in with Google)

User tokens are stored in the database. Only `credentials.json` (the OAuth
client configuration) needs to live on disk.

1. In Google Cloud, enable **Google Calendar API**.
2. Configure the Google Auth Platform consent screen — choose **External**
   for a personal account and add each test address under **Test users**.
3. Create an OAuth client of type **Web application**.
4. Register this redirect URI exactly, including the trailing slash:

   ```text
   http://localhost:8000/oauth2/callback/
   ```

5. Download the client JSON as `credentials.json` in the project root.

Configure the corresponding paths in `.env`:

```dotenv
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/oauth2/callback/
REPORT_TIME_ZONE=America/Chicago
```

`credentials.json` is gitignored and must never be committed. User access and
refresh tokens are stored in the `googlecal_googlecredential` database table.

## Database initialization

Apply the Django schema to the configured database:

```bash
.venv/bin/python manage.py migrate
```

> **Migrating from a single-user installation**
>
> Migration `calsync/0002_multi_user` drops all three calsync tables
> (`CalendarEvent`, `SyncState`, `WatchChannel`) and recreates them with
> user foreign keys. All previously synced events are deleted. After migrating,
> sign in again at `http://localhost:8000/` and the application will re-import
> the last 90 days of events automatically.

## Run the application

```bash
.venv/bin/python manage.py runserver
```

Open <http://localhost:8000/> and click **Sign in with Google**. After signing
in, the application automatically:

1. Imports the previous 90 days of events from Google Calendar.
2. Registers a Google push-notification channel so real-time sync starts.

Both steps run in a background thread; the dashboard is available immediately.
If the initial import fails for any reason, click **Sync calendar** on the
dashboard to retry.

## Real-time webhook sync — production

Set `PUBLIC_BASE_URL` to your production HTTPS domain in `.env`:

```dotenv
PUBLIC_BASE_URL=https://app.example.com
```

That is the only configuration change needed. After the next OAuth connection
(or **Sync calendar** click), the application registers a push channel pointing
at `https://app.example.com/api/webhook/` automatically. Channels expire every
seven days and are renewed on the next manual sync, so no cron job is required.

## Real-time webhook sync — local development

Google cannot deliver push notifications to `localhost`, so local development
requires an HTTPS tunnel. [ngrok](https://ngrok.com) works well.

**Step 1 — start ngrok:**

```bash
ngrok http 8000
```

ngrok prints a forwarding URL such as `https://abc123.ngrok-free.app`. If you
use a [static domain](https://ngrok.com/blog-post/free-static-domains), the URL
stays the same across restarts.

**Step 2 — sign in with Google:**

Visit `http://localhost:8000/` and click **Sign in with Google**. The
background thread runs the initial sync automatically after authorization.

**Step 3 — register the webhook channel:**

```bash
# Auto-selects the only user when there is exactly one:
.venv/bin/python manage.py dev_watch

# Or specify the user explicitly when multiple accounts exist:
.venv/bin/python manage.py dev_watch --user alice@example.com
```

`dev_watch` reads the running ngrok tunnel from its local API and registers a
push channel pointing at the tunnel URL. Run it again after ngrok restarts with
a new domain to replace the stale channel.

```bash
# Override the auto-detected URL (other tunnel providers, static domain, etc.)
.venv/bin/python manage.py dev_watch --url https://my-static.ngrok-free.app

# Stop all active channels for the user's primary calendar
.venv/bin/python manage.py dev_watch --stop
```

`dev_watch` refuses to run when `DEBUG=False`.

`ALLOWED_HOSTS` already accepts `*.ngrok-free.dev` and `*.ngrok-free.app`
subdomains in debug mode, so no further host configuration is needed.

## Sync behavior

- Webhook notifications are the primary real-time sync mechanism.
- **Sync calendar** on either dashboard is the manual backup mechanism.
- Incremental sync requests only changes since the stored Google `syncToken`.
- Missing or expired sync tokens automatically trigger a full sync.
- Google HTTP 410 responses also trigger a fresh full sync.
- Full sync reconciles events from the previous 90 days.
- The audit database stores past events; future events remain available in the
  seven-day preview directly from Google Calendar.

## Audit dashboard

Open <http://localhost:8000/api/audit/> after the initial sync. It displays:

1. Total meeting time by month
2. Months with the most and fewest meetings
3. Busiest and most relaxed weeks
4. Average meetings and meeting time per week
5. Most frequent meeting contacts
6. Recruiting and interview meeting time

Metrics use `REPORT_TIME_ZONE` for calendar bucketing while timestamps remain
stored in UTC.

## Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/` | Sign-in prompt or calendar preview (requires auth) |
| `GET` | `/oauth2/start/` | Begin Google Sign-In |
| `GET` | `/oauth2/callback/` | Complete Google Sign-In |
| `GET` | `/logout/` | Sign out |
| `POST` | `/api/sync/` | Run a CSRF-protected manual sync (requires auth) |
| `POST` | `/api/webhook/` | Receive Google push notifications |
| `GET` | `/api/audit/` | Render the audit dashboard (requires auth) |
| `GET` | `/api/audit/monthly-time/` | Monthly meeting time (requires auth) |
| `GET` | `/api/audit/meeting-extremes/` | Highest and lowest meeting months (requires auth) |
| `GET` | `/api/audit/weekly-extremes/` | Busiest and most relaxed weeks (requires auth) |
| `GET` | `/api/audit/weekly-averages/` | Weekly meeting averages (requires auth) |
| `GET` | `/api/audit/top-contacts/` | Most frequent contacts (requires auth) |
| `GET` | `/api/audit/interview-time/` | Recruiting and interview time (requires auth) |

## Useful commands

```bash
# Check database connectivity and schema
.venv/bin/python manage.py check_database

# Register a local ngrok webhook channel (DEBUG only)
.venv/bin/python manage.py dev_watch
.venv/bin/python manage.py dev_watch --user alice@example.com
.venv/bin/python manage.py dev_watch --url https://my-static.ngrok-free.app
.venv/bin/python manage.py dev_watch --stop
```

## Testing

The test suite covers OAuth helpers, calendar parsing and synchronization,
webhook validation, manual sync, watch-channel management, audit queries and
APIs, and database URL configuration.

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py test
```

Tests create a separate test database. Do not point test runs at a production
Supabase project unless the configured role is intentionally allowed to create
and destroy test databases.

## Security notes

- Never commit `.env` or `credentials.json`. User tokens are stored only in
  the database and never on disk.
- Use `sslmode=require` or Supabase's CA certificate with
  `sslmode=verify-full` for remote database traffic.
- Set `DEBUG=False`, use a strong `SECRET_KEY`, and define production
  `ALLOWED_HOSTS` before deployment.
- The Google webhook is CSRF-exempt because Google cannot supply a Django CSRF
  token; channel-token verification prevents arbitrary requests from invoking
  synchronization.
- All other authenticated endpoints are CSRF-protected.
- Each user's events, sync state, and webhook channels are isolated by a
  database-level foreign key — queries for one user cannot return another
  user's data.
