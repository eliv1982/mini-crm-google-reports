from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request, Response, status

from backend.repositories import clients as clients_repository
from backend.schemas import ClientCreate, ClientResponse, ClientStatus, ClientUpdate

router = APIRouter(prefix="/clients", tags=["clients"])


def _database_path(request: Request) -> Path:
    return request.app.state.database_path


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, request: Request) -> dict:
    return clients_repository.create_client(payload.model_dump(), _database_path(request))


@router.get("", response_model=list[ClientResponse])
def list_clients(
    request: Request,
    search: str | None = Query(default=None),
    status_filter: ClientStatus | None = Query(default=None, alias="status"),
    limit: int = Query(
        default=clients_repository.DEFAULT_LIMIT,
        ge=1,
        le=clients_repository.MAX_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return clients_repository.search_clients(
        search=search,
        status=status_filter,
        limit=limit,
        offset=offset,
        database_path=_database_path(request),
    )


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(client_id: int, request: Request) -> dict:
    return clients_repository.get_client_by_id(client_id, _database_path(request))


@router.patch("/{client_id}", response_model=ClientResponse)
def update_client(client_id: int, payload: ClientUpdate, request: Request) -> dict:
    return clients_repository.update_client(
        client_id,
        payload.model_dump(exclude_unset=True),
        _database_path(request),
    )


@router.post("/{client_id}/archive", response_model=ClientResponse)
def archive_client(client_id: int, request: Request) -> dict:
    return clients_repository.archive_client(client_id, _database_path(request))


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: int, request: Request) -> Response:
    clients_repository.delete_client(client_id, _database_path(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
