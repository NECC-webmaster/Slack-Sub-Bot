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
GCP_JSON_STR = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")


def validate_env():
    """Ensure all required environment variables are set."""
    missing = []
    for var in [
        "SLACK_BOT_TOKEN",
        "SLACK_CHANNEL_ID",
        "SPREADSHEET_ID",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
    ]:
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)


def get_target_emails_from_sheets() -> set:
    """Fetch emails from the first column of the specified Google Sheet."""
    print("Connecting to Google Sheets...")
    creds_info = json.loads(GCP_JSON_STR)
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    credentials = Credentials.from_service_account_info(
        creds_info, scopes=scopes
    )

    client = gspread.authorize(credentials)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    # Fetches all values from the first column (assumes column 1 has emails)
    emails = sheet.col_values(1)

    # Normalize emails (lowercase and strip whitespace), ignoring header if any
    cleaned_emails = {
        email.strip().lower() for email in emails if "@" in str(email)
    }
    print(
        f"Retrieved {len(cleaned_emails)} unique target emails from Google Sheets."
    )
    return cleaned_emails


def remove_matching_members(slack_client: WebClient, target_emails: set):
    """Fetch private channel members, check emails, and kick matching members."""
    print(f"Fetching members for channel {SLACK_CHANNEL_ID}...")
    try:
        # Get all member IDs in the channel
        members_response = slack_client.conversations_members(
            channel=SLACK_CHANNEL_ID
        )
        member_ids = members_response.get("members", [])
    except SlackApiError as e:
        print(f"Error fetching channel members: {e.response['error']}")
        sys.exit(1)

    print(f"Found {len(member_ids)} total members in channel.")

    removed_count = 0
    for user_id in member_ids:
        try:
            # Lookup user details
            user_info = slack_client.users_info(user=user_id)
            user_data = user_info.get("user", {})

            # Skip bots
            if user_data.get("is_bot") or user_id == "USLACKBOT":
                continue

            user_email = (
                user_data.get("profile", {}).get("email", "").strip().lower()
            )

            if user_email in target_emails:
                print(
                    f"Match found: {user_data.get('real_name', user_id)} ({user_email}). Kicking..."
                )
                slack_client.conversations_kick(
                    channel=SLACK_CHANNEL_ID, user=user_id
                )
                print(f"Successfully removed {user_id} from channel.")
                removed_count += 1

        except SlackApiError as e:
            error_code = e.response.get("error", "unknown_error")
            print(f"Failed to process/remove user {user_id}: {error_code}")

    print(
        f"\nProcess complete. Total members removed: {removed_count}"
    )


def main():
    validate_env()
    slack_client = WebClient(token=SLACK_BOT_TOKEN)

    # 1. Get emails from Google Sheets
    target_emails = get_target_emails_from_sheets()

    if not target_emails:
        print("No valid emails found in Google Sheet. Exiting.")
        return

    # 2. Check Slack members and kick matches
    remove_matching_members(slack_client, target_emails)


if __name__ == "__main__":
    main()
