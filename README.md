# Calendar Audit Tool

Reads a user's primary Google Calendar and reports how much time they spend in
meetings, and on what.

Stack: Python 3.14 / Django 6.1 / Django REST Framework / PostgreSQL 18.

## Status

Phase 1 (bootstrap and Google Calendar API smoke test) is complete. The
`calsync` and `audit` apps are registered but empty; they get filled in by the
sync engine and the report in later phases.

## Layout

```
config/       Django project: settings, URL conf, health endpoint
googlecal/    Google OAuth and API access
  oauth.py                              server-side authorization-code flow
  client.py                             load_credentials() / build_service()
  views.py                              dashboard + OAuth start/callback
  templates/googlecal/dashboard.html    auth status and event preview
  management/commands/list_events.py    prints primary-calendar events
calsync/      (empty) Phase 2: Event model, syncToken engine, push webhook
audit/        (empty) Phase 3: metrics, DRF endpoints, HTML report
scripts/
  quickstart.py   standalone API smoke test, Desktop-app clients only
```

## One-time setup

### 1. Google Cloud

1. Create or select a project at <https://console.cloud.google.com>.
2. **APIs & Services > Library > "Google Calendar API" > Enable**.
3. **Google Auth Platform > Branding > Get Started**. Set an app name and your
   email as the support email.
   - **Audience**: choose **Internal** only if the account belongs to a Google
     Workspace domain. For a personal `@gmail.com` account choose **External**,
     then add your own address under **Audience > Test users**. Skipping the
     test-user step causes `access_denied` on first login.
4. **Google Auth Platform > Clients > Create Client**. Choose **Web
   application**, and under **Authorized redirect URIs** add exactly:

   ```
   http://localhost:8000/oauth2/callback/
   ```

   The value must match `GOOGLE_OAUTH_REDIRECT_URI` character for character,
   trailing slash included, or Google returns `redirect_uri_mismatch`. Google
   permits plain `http` only for `localhost`.
5. Download the JSON and save it as `credentials.json` in the project root.

`credentials.json` and the `token.json` written after authorisation are both
gitignored. Never commit them.

A **Desktop app** client works too, but only with `scripts/quickstart.py`. It
cannot be used with the browser flow, since the desktop flow redirects to
`http://localhost:<random port>/`, which no web client can register.

### 2. Database

```bash
brew install postgresql@18
brew services start postgresql@18
brew postinstall postgresql@18       # only if the data cluster is missing
createdb calendar_audit
```

### 3. Python environment

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env                 # then edit POSTGRES_USER etc.
.venv/bin/python manage.py migrate
```

## Usage

Start the server and authorise once in the browser. Approving Google's consent
screen caches the token in `token.json`, after which every other entry point
works:

```bash
.venv/bin/python manage.py runserver
```

Then open <http://localhost:8000/> and click **Connect Google Calendar**. The
page then shows your primary calendar and the next 7 days of events.

| Route | Purpose |
| --- | --- |
| `/` | Auth status and event preview |
| `/oauth2/start/` | Redirects to Google's consent screen |
| `/oauth2/callback/` | Exchanges the code for tokens |
| `/api/health/` | `{"status": "ok", "database": "ok"}` |

The same calendar is readable from the command line once authorised:

```bash
.venv/bin/python manage.py list_events --days 7          # next 7 days
.venv/bin/python manage.py list_events --days 30 --past  # last 30 days
```

## Notes

- OAuth scopes are `openid`, `userinfo.email` and `calendar.readonly`.
  `calendar.readonly` covers both `events.list` and `events.watch`, so no
  broader grant is needed. Changing `GOOGLE_OAUTH_SCOPES` invalidates
  `token.json`; delete it and re-authorise.
- The flow requests `access_type=offline` with `prompt=consent` so Google
  returns a refresh token, which the sync engine needs to poll without the
  user present. It also uses PKCE.
- Two `oauthlib` restrictions are relaxed in `config/settings.py`:
  `OAUTHLIB_INSECURE_TRANSPORT` (only when `DEBUG` and the callback is plain
  http, since the localhost callback is not HTTPS) and
  `OAUTHLIB_RELAX_TOKEN_SCOPE` (Google echoes the granted scopes back in a
  different order for `openid` requests, which oauthlib otherwise treats as a
  scope-change attack).
- Event fetches use `singleEvents=True`, which expands recurring events into
  individual instances. The audit metrics need actual occurrences, not rules.
- Calendar data is handled in UTC. `REPORT_TIME_ZONE` only affects how events
  are displayed and how they are bucketed into weeks and months.
- Phase 2 freshness: `events.watch` push notifications will trigger a
  `syncToken`-based incremental fetch. Notifications carry no payload and are
  not fully reliable, so a periodic full-sync safety net is also required. The
  webhook needs a public HTTPS URL with a valid certificate, so a tunnel
  (ngrok or cloudflared) is needed for local development.
