from __future__ import annotations

from datetime import datetime, timezone

from google_integration import (
    ConfigError,
    GoogleDriveClient,
    GoogleDriveOperationError,
    load_google_drive_config,
)


def main() -> None:
    config = load_google_drive_config()
    if not config.drive_folder_id:
        raise ConfigError(
            "GOOGLE_DRIVE_FOLDER_ID must be set before running the Google Drive smoke test."
        )

    client = GoogleDriveClient.from_config(config)
    created_file_id: str | None = None

    try:
        client.authenticate()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        created_file = client.create_google_spreadsheet(
            name=f"mini-crm-smoke-{timestamp}",
            parent_folder_id=config.drive_folder_id,
        )
        created_file_id = created_file["id"]

        fetched_file = client.get_file(created_file_id)
        if fetched_file.get("id") != created_file_id:
            raise GoogleDriveOperationError(
                "Smoke test failed because fetched file metadata does not match the created file."
            )

        print(f"File name: {created_file.get('name', '')}")
        print(f"File ID: {created_file_id}")
        print(f"Web view link: {created_file.get('webViewLink', '')}")
    finally:
        if created_file_id:
            client.delete_file(created_file_id)
            print("Cleanup: deleted smoke-test file.")


if __name__ == "__main__":
    main()
