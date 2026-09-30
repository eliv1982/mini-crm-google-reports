from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ClientStatus = Literal["active", "archived"]
DealStatus = Literal["new", "in_progress", "won", "lost"]


def _strip_or_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _reject_null(value: object) -> object:
    # Update fields default to "unset", so this only runs for an explicit null.
    if value is None:
        raise ValueError("must not be null; omit the field to leave it unchanged")
    return value


def _validate_iso_date(value: str | None) -> str | None:
    # Dates stay plain YYYY-MM-DD strings; only the format is enforced.
    if value is None:
        return None
    try:
        is_valid = date.fromisoformat(value).isoformat() == value
    except ValueError:
        is_valid = False
    if not is_valid:
        raise ValueError("must be a valid calendar date in YYYY-MM-DD format")
    return value


class BaseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClientCreate(BaseSchema):
    name: str = Field(..., min_length=1)
    company: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    status: ClientStatus = "active"

    @field_validator("company", "email", "phone", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value: object) -> object:
        return _strip_or_none(value)


class ClientUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1)
    company: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    status: ClientStatus | None = None

    @field_validator("company", "email", "phone", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value: object) -> object:
        return _strip_or_none(value)

    @field_validator("name", "status", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        return _reject_null(value)


class ClientResponse(BaseSchema):
    id: int
    name: str
    company: str | None
    email: EmailStr | None
    phone: str | None
    status: ClientStatus
    created_at: str
    updated_at: str


class DealCreate(BaseSchema):
    title: str = Field(..., min_length=1)
    client_id: int | None = Field(default=None, ge=1)
    amount: float = Field(default=0, ge=0)
    status: DealStatus = "new"
    expected_close_date: str | None = None

    @field_validator("expected_close_date", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value: object) -> object:
        return _strip_or_none(value)

    @field_validator("expected_close_date")
    @classmethod
    def validate_expected_close_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class DealUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=1)
    client_id: int | None = Field(default=None, ge=1)
    amount: float | None = Field(default=None, ge=0)
    status: DealStatus | None = None
    expected_close_date: str | None = None

    @field_validator("expected_close_date", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value: object) -> object:
        return _strip_or_none(value)

    @field_validator("title", "amount", "status", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        return _reject_null(value)

    @field_validator("expected_close_date")
    @classmethod
    def validate_expected_close_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class DealResponse(BaseSchema):
    id: int
    title: str
    client_id: int | None
    amount: float
    status: DealStatus
    expected_close_date: str | None
    created_at: str
    updated_at: str


class TaskCreate(BaseSchema):
    title: str = Field(..., min_length=1)
    description: str | None = None
    client_id: int | None = Field(default=None, ge=1)
    deal_id: int | None = Field(default=None, ge=1)
    due_date: str | None = None

    @field_validator("description", "due_date", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value: object) -> object:
        return _strip_or_none(value)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class TaskUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    client_id: int | None = Field(default=None, ge=1)
    deal_id: int | None = Field(default=None, ge=1)
    due_date: str | None = None

    @field_validator("description", "due_date", mode="before")
    @classmethod
    def normalize_optional_fields(cls, value: object) -> object:
        return _strip_or_none(value)

    @field_validator("title", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        return _reject_null(value)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class TaskResponse(BaseSchema):
    id: int
    title: str
    description: str | None
    client_id: int | None
    deal_id: int | None
    due_date: str | None
    completed: bool
    created_at: str
    updated_at: str
