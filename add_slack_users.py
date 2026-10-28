import json
import os
import sys
import gspread
from google.oauth2.service_account import Credentials
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Load configuration from environment variables
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SHEET_TAB_NAME = os.environ.get("SHEET_TAB_NAME")
GCP_JSON_STR = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")


def validate_env():
    """Ensure all required environment variables are set."""
    missing = []
    required_vars = [
        "SLACK_BOT_TOKEN",
        "SLACK_CHANNEL_ID",
        "SPREADSHEET_ID",
        "SHEET_TAB_NAME",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
    ]
    for var in required_vars:
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)


def get_target_emails_from_sheets() -> set:
    """Fetch emails from Column A of the Google Sheet tab, skipping row 1 (header)."""
    print(f"Connecting to Google Sheets (Tab: '{SHEET_TAB_NAME}')...")
    creds_info = json.loads(GCP_JSON_STR)
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    credentials = Credentials.from_service_account_info(
        creds_info, scopes=scopes
    )

    client = gspread.authorize(credentials)

    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet(SHEET_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        print(f"Error: Worksheet tab named '{SHEET_TAB_NAME}' was not found.")
        sys.exit(1)

    column_a_values = worksheet.col_values(1)

    if len(column_a_values) <= 1:
        print("No emails found below header row.")
        return set()

    # Skip header (A1)
    data_rows = column_a_values[1:]

    cleaned_emails = {
        email.strip().lower() for email in data_rows if "@" in str(email)
    }

    print(
        f"Retrieved {len(cleaned_emails)} unique target emails from Google Sheets."
    )
    return cleaned_emails


def add_users_to_channel(slack_client: WebClient, target_emails: set):
    """Look up users by email and invite them to the Slack channel."""
    print(f"Processing invitations for channel {SLACK_CHANNEL_ID}...")

    added_count = 0
    already_in_channel_count = 0

    for email in target_emails:
        try:
            # Look up Slack User ID by email
            user_response = slack_client.users_lookupByEmail(email=email)
            user_data = user_response.get("user", {})
            user_id = user_data.get("id")

            if not user_id:
                print(f"Warning: Could not resolve Slack User ID for {email}")
                continue

            # Invite user to channel
            slack_client.conversations_invite(
                channel=SLACK_CHANNEL_ID, users=user_id
            )
            print(f"Successfully added {email} ({user_id}) to channel.")
            added_count += 1

        except SlackApiError as e:
            error_code = e.response.get("error", "unknown_error")
            if error_code == "already_in_channel":
                print(f"Skip: {email} is already in the channel.")
                already_in_channel_count += 1
            elif error_code == "user_not_found":
                print(f"Error: No Slack user found matching email '{email}'.")
            elif error_code == "cant_invite_self":
                print(f"Skip: Cannot invite bot user itself ({email}).")
            else:
                print(f"Failed to add {email}: {error_code}")

    print(f"\nProcess complete.")
    print(f"- Users newly added: {added_count}")
    print(f"- Users already present: {already_in_channel_count}")


def main():
    validate_env()
    slack_client = WebClient(token=SLACK_BOT_TOKEN)

    # 1. Fetch emails to invite
    target_emails = get_target_emails_from_sheets()

    if not target_emails:
        print("No valid emails found in sheet. Exiting.")
        return

    # 2. Add matching users to channel
    add_users_to_channel(slack_client, target_emails)


if __name__ == "__main__":
    main()
