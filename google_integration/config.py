from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required Google integration configuration is missing or invalid."""


@dataclass(frozen=True)
class GoogleSheetsConfig:
    credentials_path: Path


@dataclass(frozen=True)
class GoogleDriveConfig:
    client_secret_path: Path
    token_path: Path
    drive_folder_id: str | None


def _load_project_root(env_file: Path | None = None) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = env_file or project_root / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=False)
    return project_root


def _get_required_env_path(
    variable_name: str,
    project_root: Path,
    *,
    missing_message: str,
    not_found_message: str | None = None,
) -> Path:
    raw_path = os.getenv(variable_name, "").strip()
    if not raw_path:
        raise ConfigError(missing_message)

    resolved_path = Path(raw_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = project_root / resolved_path

    if not_found_message and not resolved_path.is_file():
        raise ConfigError(not_found_message)

    return resolved_path.resolve(strict=False)


def load_google_sheets_config(env_file: Path | None = None) -> GoogleSheetsConfig:
    project_root = _load_project_root(env_file=env_file)
    credentials_path = _get_required_env_path(
        "GOOGLE_SERVICE_ACCOUNT_PATH",
        project_root,
        missing_message="Required environment variable GOOGLE_SERVICE_ACCOUNT_PATH is not set.",
        not_found_message=(
            "Google service account file was not found. "
            "Check GOOGLE_SERVICE_ACCOUNT_PATH."
        ),
    )
    return GoogleSheetsConfig(credentials_path=credentials_path.resolve())


def load_google_drive_config(env_file: Path | None = None) -> GoogleDriveConfig:
    project_root = _load_project_root(env_file=env_file)
    client_secret_path = _get_required_env_path(
        "GOOGLE_OAUTH_CLIENT_SECRET_PATH",
        project_root,
        missing_message=(
            "Required environment variable GOOGLE_OAUTH_CLIENT_SECRET_PATH is not set."
        ),
        not_found_message=(
            "Google OAuth client secret file was not found. "
            "Check GOOGLE_OAUTH_CLIENT_SECRET_PATH."
        ),
    )
    token_path = _get_required_env_path(
        "GOOGLE_OAUTH_TOKEN_PATH",
        project_root,
        missing_message="Required environment variable GOOGLE_OAUTH_TOKEN_PATH is not set.",
    )
    drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip() or None

    return GoogleDriveConfig(
        client_secret_path=client_secret_path,
        token_path=token_path,
        drive_folder_id=drive_folder_id,
    )
