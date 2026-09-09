"""Smoke-test Google Calendar access without starting Django.

The script loads or creates credentials for a desktop OAuth client, builds a
Calendar API service, and prints the next ten primary-calendar events. Web OAuth
clients must use the Django browser flow because their redirect URI is fixed.
"""

import datetime
import json
import os.path
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Request identity details and read-only calendar access.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Resolve OAuth files from the project root, not the current shell directory.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")


def get_credentials():
    """Return valid desktop OAuth credentials for the smoke test.

    A saved token is reused or refreshed when possible. Otherwise the client file
    is validated and a temporary localhost browser flow collects authorization.
    New or refreshed credentials are saved for later runs.
    """
    creds = None
    
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                sys.exit(
                    f"Missing {CREDENTIALS_FILE}.\n"
                    "Download the OAuth 2.0 Client ID JSON from the Google "
                    "Cloud console and save it there."
                )
            
            # This standalone loopback flow cannot serve a fixed web callback.
            with open(CREDENTIALS_FILE) as handle:
                if "web" in json.load(handle):
                    sys.exit(
                        "This is a 'web' OAuth client, which cannot use the "
                        "loopback flow this script relies on (Google rejects it "
                        "with redirect_uri_mismatch).\n"
                        "Authorise through Django instead:\n"
                        "  .venv/bin/python manage.py runserver\n"
                        "  then open http://localhost:8000/"
                    )
            
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


def main():
    """Print primary-calendar details and the next ten events.

    The function authenticates, calls Google's calendars and events endpoints,
    expands recurring meetings, and exits with a readable API error on failure.
    """
    creds = get_credentials()

    try:
        service = build("calendar", "v3", credentials=creds)

        calendar = service.calendars().get(calendarId="primary").execute()
        print(f"Primary calendar: {calendar.get('id')} ({calendar.get('timeZone')})")

        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        print("\nGetting the upcoming 10 events")
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=10,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        if not events:
            print("No upcoming events found.")
            return

        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            print(start, event.get("summary", "(no title)"))
            
    except HttpError as error:
        sys.exit(f"An error occurred: {error}")


if __name__ == "__main__":
    main()
