from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.database import initialize_database, resolve_database_path
from backend.repositories.errors import (
    DatabaseOperationError,
    EntityNotFoundError,
    InvalidReferenceError,
)
from backend.routers import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database(app.state.database_path)
    yield


def create_app(database_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Mini CRM API", lifespan=lifespan)
    app.state.database_path = resolve_database_path(database_path)

    @app.exception_handler(EntityNotFoundError)
    async def handle_not_found(
        request: Request,
        exc: EntityNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(InvalidReferenceError)
    async def handle_invalid_reference(
        request: Request,
        exc: InvalidReferenceError,
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(DatabaseOperationError)
    async def handle_database_error(
        request: Request,
        exc: DatabaseOperationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": "A database operation failed."},
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    return app


app = create_app()
