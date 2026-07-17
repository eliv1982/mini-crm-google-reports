from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ClientStatus = Literal["active", "archived"]
DealStatus = Literal["new", "in_progress", "won", "lost"]


def _strip_or_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
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
