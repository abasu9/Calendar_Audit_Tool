# Calendar Audit Tool

A Django application that connects to a user's primary Google Calendar,
synchronizes recent events into PostgreSQL, and presents a dashboard of meeting
habits and time allocation.

The primary data-refresh path is a Google Calendar push webhook. Users can also
request an on-demand sync from either dashboard when a notification is missed
or delayed. There is no periodic scheduler.

## Features

- Connect a Google Calendar securely
- Preview events for the next seven days
- Keep calendar data current through real-time webhooks
- Refresh calendar data manually when needed
- Store calendar data in Supabase or local PostgreSQL
- Review meeting trends from the previous three months
- Use the dashboards on desktop and mobile

## Implementation phases

### Phase 1 — Google Calendar connection

- Set up the Django project and Google Calendar API client
- Add the Google OAuth authorization flow
- Display the connected calendar and upcoming events
- Add command-line tools for testing calendar access

### Phase 2 — Calendar synchronization

- Store calendar events in PostgreSQL
- Add initial full sync and incremental sync
- Track Google sync tokens and recover from expired tokens
- Receive real-time updates through Google push notifications
- Add manual dashboard sync as a backup

### Phase 3 — Calendar audit

- Calculate monthly meeting time and meeting counts
- Identify busiest and most relaxed weeks
- Calculate weekly meeting averages
- Find the most frequent meeting contacts
- Measure recruiting and interview time
- Expose the results through APIs and the audit dashboard

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
  api_urls.py             API route composition

googlecal/
  client.py               Credential loading and Google API client
  oauth.py                OAuth authorization-code flow
  views.py                Main dashboard and OAuth callbacks
  templates/              Connected-calendar dashboard
  management/commands/    Calendar preview command

calsync/
  models.py               Events, sync state, and watch channels
  sync.py                 Full and incremental synchronization
  watch.py                Google push-channel management
  views.py                Manual sync and webhook endpoints
  management/commands/    Calendar sync and watch utilities

calaudit/
  queries.py              Calendar analytics queries
  views.py                Audit API views and dashboard
  templates/              Audit dashboard

scripts/
  quickstart.py           Standalone Google API smoke test
  simulate_push.py        Local webhook simulation helper
```

## Prerequisites

- Python 3.14
- A Google Cloud project with the Google Calendar API enabled
- A Supabase project or local PostgreSQL database
- ngrok or another public HTTPS tunnel for local webhook delivery

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
URL. A transaction-pooler URI on port `6543` is also supported; the database
utility automatically disables prepared statements and server-side cursors
for that mode.

When `DATABASE_URL` is absent, the application uses these local PostgreSQL
settings instead:

```dotenv
POSTGRES_DB=calendar_audit
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### Google OAuth

1. In Google Cloud, enable **Google Calendar API**.
2. Configure the Google Auth Platform consent screen.
3. For a personal Google account, select an external audience and add the
   account under **Test users**.
4. Create an OAuth client of type **Web application**.
5. Register this redirect URI exactly, including the trailing slash:

   ```text
   http://localhost:8000/oauth2/callback/
   ```

6. Download the client JSON as `credentials.json` in the project root.

Configure the corresponding paths in `.env`:

```dotenv
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/oauth2/callback/
REPORT_TIME_ZONE=America/Chicago
```

The browser flow writes `token.json` after authorization. Both credential files
are gitignored and must never be committed.

## Database initialization

Apply the Django schema to the configured database:

```bash
.venv/bin/python manage.py migrate
```

Switching from local PostgreSQL to Supabase creates an empty database. Migrations
create the tables but do not copy local events, sync tokens, sessions, or watch
channels.

## Run the application

Start Django:

```bash
.venv/bin/python manage.py runserver
```

Open <http://localhost:8000/> and select **Connect Google Calendar**. After
authorization, perform the initial sync from the dashboard or the command line:

```bash
.venv/bin/python manage.py sync_calendar --full
```

The initial full sync imports the previous 90 days and establishes the Google
`syncToken` used by later incremental syncs.

## Configure real-time webhook sync

Google requires a publicly reachable HTTPS endpoint. For local development,
start a tunnel that forwards to Django's actual port:

```bash
ngrok http 8000
```

Confirm that ngrok reports a forwarding target of `http://localhost:8000`, then
register its current HTTPS URL:

```bash
.venv/bin/python manage.py setup_watch \
  --url https://YOUR-NGROK-HOST/api/webhook/
```

Inspect or stop active channels with:

```bash
.venv/bin/python manage.py stop_watch --list
.venv/bin/python manage.py stop_watch --channel-id CHANNEL_UUID
.venv/bin/python manage.py stop_watch --all
```

Watch channels expire and Google does not renew them automatically. Register a
replacement before expiration. Avoid multiple active channels for the same
calendar and webhook URL, since each channel produces its own notification.

When the application database changes, such as moving from local PostgreSQL to
Supabase, register a new channel so its verification token and resource ID are
stored in the new database.

## Sync behavior

- Webhook notifications are the primary real-time sync mechanism.
- **Sync calendar** on either dashboard is the manual backup mechanism.
- Incremental sync requests only changes since the stored Google `syncToken`.
- Missing or expired sync tokens automatically trigger a full sync.
- Google HTTP 410 responses also trigger a fresh full sync.
- Full sync reconciles events from the previous 90 days.
- The audit database stores past events; future events remain available in the
  seven-day preview directly from Google Calendar.

There is intentionally no cron job or periodic synchronization command.

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
| `GET` | `/` | OAuth status, calendar preview, and manual sync |
| `GET` | `/oauth2/start/` | Begin Google authorization |
| `GET` | `/oauth2/callback/` | Complete Google authorization |
| `POST` | `/api/sync/` | Run a CSRF-protected manual sync |
| `POST` | `/api/webhook/` | Receive Google push notifications |
| `GET` | `/api/audit/` | Render the audit dashboard |
| `GET` | `/api/audit/monthly-time/` | Monthly meeting time |
| `GET` | `/api/audit/meeting-extremes/` | Highest and lowest meeting months |
| `GET` | `/api/audit/weekly-extremes/` | Busiest and most relaxed weeks |
| `GET` | `/api/audit/weekly-averages/` | Weekly meeting averages |
| `GET` | `/api/audit/top-contacts/` | Most frequent contacts |
| `GET` | `/api/audit/interview-time/` | Recruiting and interview time |

## Useful commands

```bash
# Initial or forced full calendar sync
.venv/bin/python manage.py sync_calendar --full

# Incremental sync, with automatic full-sync fallback
.venv/bin/python manage.py sync_calendar

# Preview upcoming or past events directly from Google
.venv/bin/python manage.py list_events --days 7
.venv/bin/python manage.py list_events --days 30 --past

# Exercise a locally running webhook with a stored watch channel
.venv/bin/python manage.py test_webhook
```

## Testing

The test suite covers OAuth helpers, calendar parsing and synchronization,
webhook validation, manual sync, audit queries and APIs, and database URL
configuration.

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py test
```

Tests create a separate test database. Do not point test runs at a production
Supabase project unless the configured role is intentionally allowed to create
and destroy test databases.

## Security notes

- Never commit `.env`, `credentials.json`, or `token.json`.
- Use `sslmode=require` or Supabase's CA certificate with
  `sslmode=verify-full` for remote database traffic.
- Set `DEBUG=False`, use a strong `SECRET_KEY`, and define production
  `ALLOWED_HOSTS` before deployment.
- The Google webhook is CSRF-exempt because Google cannot supply a Django CSRF
  token; channel-token verification prevents arbitrary requests from invoking
  synchronization.
- The manual sync endpoint remains CSRF-protected.
