"""
Standalone Google Calendar API Smoke Test

PURPOSE:
A simple script to test Google Calendar API connectivity WITHOUT Django.
If this works, you know the Google Cloud project, OAuth client, and consent
screen are configured correctly.

IMPORTANT: This script only works with "Desktop app" OAuth clients!
If your credentials.json has type "web", you'll get redirect_uri_mismatch.
Use the Django web flow instead: python manage.py runserver, then visit localhost:8000

HOW IT WORKS:
1. Load or create OAuth credentials (opens browser for consent if needed)
2. Build a Google Calendar API client
3. Fetch and print the next 10 events from your primary calendar

USAGE:
    cd /path/to/project
    .venv/bin/python scripts/quickstart.py

FILES:
- credentials.json: OAuth client config (download from Google Cloud Console)
- token.json: User's access/refresh tokens (created after first authorization)
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

# OAuth scopes (permissions) we request
# - calendar.readonly: Read calendar events
# - openid + userinfo.email: Get user's identity
# Changing these scopes invalidates token.json - delete it and re-authorize
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# File paths relative to project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")


def get_credentials():
    """
    Load or obtain Google OAuth credentials.
    
    CREDENTIAL LOADING LOGIC:
    1. If token.json exists: load credentials from it
    2. If credentials are valid: return them immediately
    3. If credentials are expired but have refresh_token: refresh them
    4. If no valid credentials: start the desktop OAuth flow (opens browser)
    
    DESKTOP OAUTH FLOW:
    - Opens your browser to Google's consent screen
    - Starts a temporary local web server on a random port
    - Google redirects to http://localhost:<port>/ after you consent
    - The flow captures the authorization code and exchanges it for tokens
    - This ONLY works with "installed" type OAuth clients (Desktop app)
    
    RETURNS:
    - google.oauth2.credentials.Credentials object
    
    EXITS WITH ERROR IF:
    - credentials.json is missing
    - credentials.json is a "web" type (wrong client type for this script)
    """
    creds = None
    
    # Step 1: Try to load existing token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # Step 2: Check if we need to refresh or re-authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token expired but we have refresh_token - refresh it
            creds.refresh(Request())
        else:
            # No valid credentials - need to authorize
            
            # Check that credentials.json exists
            if not os.path.exists(CREDENTIALS_FILE):
                sys.exit(
                    f"Missing {CREDENTIALS_FILE}.\n"
                    "Download the OAuth 2.0 Client ID JSON from the Google "
                    "Cloud console and save it there."
                )
            
            # Check that it's a Desktop app, not Web application
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
            
            # Run the desktop OAuth flow
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)  # port=0 = pick random available port

        # Save the credentials for next time
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return creds


def main():
    """
    Main function: fetch and print upcoming calendar events.
    
    WHAT THIS DOES:
    1. Get valid OAuth credentials
    2. Build a Google Calendar API client
    3. Get the primary calendar's metadata (email, timezone)
    4. Fetch the next 10 events
    5. Print them to the console
    
    API CALLS MADE:
    - calendars().get(calendarId="primary"): Get calendar info
    - events().list(...): Get upcoming events
      - singleEvents=True: Expand recurring events
      - orderBy="startTime": Sort chronologically
    """
    creds = get_credentials()

    try:
        # Build the API client
        service = build("calendar", "v3", credentials=creds)

        # Get primary calendar info
        calendar = service.calendars().get(calendarId="primary").execute()
        print(f"Primary calendar: {calendar.get('id')} ({calendar.get('timeZone')})")

        # Get upcoming events
        now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        print("\nGetting the upcoming 10 events")
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,  # Only future events
                maxResults=10,
                singleEvents=True,  # Expand recurring events
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        # Print events
        if not events:
            print("No upcoming events found.")
            return

        for event in events:
            # Get start time (dateTime for timed events, date for all-day)
            start = event["start"].get("dateTime", event["start"].get("date"))
            print(start, event.get("summary", "(no title)"))
            
    except HttpError as error:
        sys.exit(f"An error occurred: {error}")


if __name__ == "__main__":
    main()
