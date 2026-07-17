from fastapi import APIRouter

from .clients import router as clients_router
from .deals import router as deals_router
from .tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(clients_router)
api_router.include_router(deals_router)
api_router.include_router(tasks_router)
