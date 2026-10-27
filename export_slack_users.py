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


def fetch_channel_member_emails(slack_client: WebClient) -> list:
    """Fetch all human members in the specified channel and extract their emails."""
    print(f"Fetching member IDs for channel {SLACK_CHANNEL_ID}...")
    try:
        members_response = slack_client.conversations_members(
            channel=SLACK_CHANNEL_ID
        )
        member_ids = members_response.get("members", [])
    except SlackApiError as e:
        print(f"Error fetching channel members: {e.response['error']}")
        sys.exit(1)

    print(f"Found {len(member_ids)} raw member entries. Fetching user profiles...")

    emails = []
    for user_id in member_ids:
        try:
            user_info = slack_client.users_info(user=user_id)
            user_data = user_info.get("user", {})

            # Skip bots and deleted users
            if (
                user_data.get("is_bot")
                or user_data.get("deleted")
                or user_id == "USLACKBOT"
            ):
                continue

            email = user_data.get("profile", {}).get("email")
            if email:
                emails.append(email.strip().lower())

        except SlackApiError as e:
            print(f"Warning: Failed to fetch profile for user {user_id}: {e.response.get('error')}")

    print(f"Successfully retrieved {len(emails)} valid member emails.")
    return emails


def write_emails_to_google_sheet(emails: list):
    """Overwrite Column A of the specified worksheet tab with the header and emails."""
    print(f"Connecting to Google Sheets (Tab: '{SHEET_TAB_NAME}')...")
    creds_info = json.loads(GCP_JSON_STR)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
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

    # Format values as a list of 1-element lists for column insertion
    # Row 1 is header "Email", followed by the emails
    cell_values = [["Email"]] + [[email] for email in sorted(set(emails))]

    print(f"Clearing Column A in '{SHEET_TAB_NAME}'...")
    # Clear existing content in Column A to prevent trailing leftover rows
    worksheet.batch_clear(["A:A"])

    print(f"Writing {len(cell_values) - 1} unique email addresses to Column A...")
    # Update Column A starting at A1
    worksheet.update(values=cell_values, range_name="A1")
    print("Google Sheet updated successfully!")


def main():
    validate_env()
    slack_client = WebClient(token=SLACK_BOT_TOKEN)

    # 1. Fetch channel members' emails
    emails = fetch_channel_member_emails(slack_client)

    if not emails:
        print("No member emails found in channel. Exiting.")
        return

    # 2. Populate Google Sheet tab
    write_emails_to_google_sheet(emails)


if __name__ == "__main__":
    main()
