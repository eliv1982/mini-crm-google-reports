from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request, Response, status

from backend.repositories import tasks as tasks_repository
from backend.schemas import TaskCreate, TaskResponse, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _database_path(request: Request) -> Path:
    return request.app.state.database_path


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, request: Request) -> dict:
    return tasks_repository.create_task(payload.model_dump(), _database_path(request))


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    request: Request,
    search: str | None = Query(default=None),
    client_id: int | None = Query(default=None, ge=1),
    deal_id: int | None = Query(default=None, ge=1),
    completed: bool | None = Query(default=None),
    limit: int = Query(
        default=tasks_repository.DEFAULT_LIMIT,
        ge=1,
        le=tasks_repository.MAX_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return tasks_repository.search_tasks(
        search=search,
        client_id=client_id,
        deal_id=deal_id,
        completed=completed,
        limit=limit,
        offset=offset,
        database_path=_database_path(request),
    )


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, request: Request) -> dict:
    return tasks_repository.get_task_by_id(task_id, _database_path(request))


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, payload: TaskUpdate, request: Request) -> dict:
    return tasks_repository.update_task(
        task_id,
        payload.model_dump(exclude_unset=True),
        _database_path(request),
    )


@router.post("/{task_id}/complete", response_model=TaskResponse)
def complete_task(task_id: int, request: Request) -> dict:
    return tasks_repository.set_task_completed(task_id, True, _database_path(request))


@router.post("/{task_id}/reopen", response_model=TaskResponse)
def reopen_task(task_id: int, request: Request) -> dict:
    return tasks_repository.set_task_completed(task_id, False, _database_path(request))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, request: Request) -> Response:
    tasks_repository.delete_task(task_id, _database_path(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
