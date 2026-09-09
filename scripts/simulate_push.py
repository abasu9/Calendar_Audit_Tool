#!/usr/bin/env python
"""Simulate a Google Calendar push notification during local development.

The script posts Google's webhook header format to a running application. A real
saved channel ID and token are still required so the normal security checks and
incremental sync path are tested.
"""

import argparse
import sys

import requests

# Replace these placeholders or pass matching saved-channel values as options.
CHANNEL_ID = "your-channel-id-here"
RESOURCE_ID = "mock-resource-id"
TOKEN = "your-token-here"

WEBHOOK_URL = "http://localhost:8000/api/webhook/"


def simulate_push(
    channel_id: str,
    resource_id: str,
    token: str,
    webhook_url: str,
    state: str = "exists",
    message_number: int = 2,
):
    """Send one Google-shaped notification to the chosen webhook URL.

    Channel, resource, state, token, and message values become request headers; the
    body stays empty like Google's real request. The response is printed and a
    connection failure exits with a nonzero status.
    """
    headers = {
        "X-Goog-Channel-ID": channel_id,
        "X-Goog-Resource-ID": resource_id,
        "X-Goog-Resource-State": state,
        "X-Goog-Channel-Token": token,
        "X-Goog-Message-Number": str(message_number),
        "Content-Type": "application/json; utf-8",
    }
    
    print(f"Sending simulated push notification...")
    print(f"  URL: {webhook_url}")
    print(f"  Channel ID: {channel_id}")
    print(f"  Resource State: {state}")
    print(f"  Message Number: {message_number}")
    print()
    
    try:
        response = requests.post(
            webhook_url,
            headers=headers,
            data="",
            timeout=30,
        )
        
        print(f"Response:")
        print(f"  Status: {response.status_code}")
        print(f"  Body: {response.text}")
        
        if response.status_code == 200:
            print()
            print("✓ Webhook accepted the notification!")
            print("  Check the server logs to see if sync was triggered.")
        elif response.status_code == 403:
            print()
            print("✗ Token verification failed!")
            print("  Make sure CHANNEL_ID and TOKEN match a WatchChannel record.")
            print("  Or create a channel with: python manage.py setup_watch --url http://localhost:8000/api/webhook/")
        else:
            print()
            print(f"✗ Unexpected response code: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print()
        print("✗ Could not connect to webhook URL!")
        print("  Is the Django server running?")
        print("  Start it with: python manage.py runserver")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"✗ Error: {e}")
        sys.exit(1)


def main():
    """Parse command options, warn about placeholders, and run the simulation.

    Defaults support a local Django server. Explicit values let the same script use
    any saved channel or reachable webhook endpoint.
    """
    parser = argparse.ArgumentParser(
        description="Simulate Google Calendar push notifications for testing."
    )
    parser.add_argument(
        "--channel-id",
        type=str,
        default=CHANNEL_ID,
        help="Channel ID (UUID) to use.",
    )
    parser.add_argument(
        "--resource-id",
        type=str,
        default=RESOURCE_ID,
        help="Resource ID to use.",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=TOKEN,
        help="Token for verification.",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=WEBHOOK_URL,
        help="Webhook URL to POST to.",
    )
    parser.add_argument(
        "--state",
        type=str,
        choices=["sync", "exists"],
        default="exists",
        help="Resource state (sync=initial, exists=changes).",
    )
    parser.add_argument(
        "--message-number",
        type=int,
        default=2,
        help="Message number (1=sync, 2+=changes).",
    )
    
    args = parser.parse_args()
    
    # Placeholder credentials cannot pass webhook verification.
    if args.channel_id == "your-channel-id-here":
        print("=" * 60)
        print("WARNING: Using placeholder CHANNEL_ID!")
        print()
        print("To get real values, either:")
        print("  1. Run: python manage.py setup_watch --url http://localhost:8000/api/webhook/")
        print("  2. Check your WatchChannel records in the database")
        print()
        print("Then update the CHANNEL_ID, RESOURCE_ID, and TOKEN in this script,")
        print("or pass them as command-line arguments.")
        print("=" * 60)
        print()
    
    simulate_push(
        channel_id=args.channel_id,
        resource_id=args.resource_id,
        token=args.token,
        webhook_url=args.url,
        state=args.state,
        message_number=args.message_number,
    )


if __name__ == "__main__":
    main()
