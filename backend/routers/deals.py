from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request, Response, status

from backend.repositories import deals as deals_repository
from backend.schemas import DealCreate, DealResponse, DealStatus, DealUpdate

router = APIRouter(prefix="/deals", tags=["deals"])


def _database_path(request: Request) -> Path:
    return request.app.state.database_path


@router.post("", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
def create_deal(payload: DealCreate, request: Request) -> dict:
    return deals_repository.create_deal(payload.model_dump(), _database_path(request))


@router.get("", response_model=list[DealResponse])
def list_deals(
    request: Request,
    search: str | None = Query(default=None),
    client_id: int | None = Query(default=None, ge=1),
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(
        default=deals_repository.DEFAULT_LIMIT,
        ge=1,
        le=deals_repository.MAX_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return deals_repository.search_deals(
        search=search,
        client_id=client_id,
        status=status_filter,
        limit=limit,
        offset=offset,
        database_path=_database_path(request),
    )


@router.get("/{deal_id}", response_model=DealResponse)
def get_deal(deal_id: int, request: Request) -> dict:
    return deals_repository.get_deal_by_id(deal_id, _database_path(request))


@router.patch("/{deal_id}", response_model=DealResponse)
def update_deal(deal_id: int, payload: DealUpdate, request: Request) -> dict:
    return deals_repository.update_deal(
        deal_id,
        payload.model_dump(exclude_unset=True),
        _database_path(request),
    )


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(deal_id: int, request: Request) -> Response:
    deals_repository.delete_deal(deal_id, _database_path(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
