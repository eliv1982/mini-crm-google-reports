from __future__ import annotations


class RepositoryError(RuntimeError):
    """Base repository exception."""


class EntityNotFoundError(RepositoryError):
    def __init__(self, entity_name: str, entity_id: int) -> None:
        super().__init__(f"{entity_name} with id {entity_id} was not found.")


class InvalidReferenceError(RepositoryError):
    def __init__(self, field_name: str, field_value: int) -> None:
        super().__init__(f"Invalid reference for {field_name}: {field_value}.")


class DatabaseOperationError(RepositoryError):
    """Raised when a database operation fails."""
