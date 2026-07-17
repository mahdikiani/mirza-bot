"""FastAPI application factory and router registration."""

from fastapi import APIRouter
from fastapi_mongo_base.core import app_factory

from apps.ai.routes import router as ai_router
from apps.ai.task_poller import start_task_poller
from apps.bots.bale.routes import router as bale_router
from apps.bots.runtime.handlers import BotHandler

from . import config

app = app_factory.create_app(
    settings=config.Settings(),
    init_functions=[BotHandler().setup, start_task_poller],
)

server_router = APIRouter()

for router in [bale_router, ai_router]:
    server_router.include_router(router)

app.include_router(server_router, prefix=config.Settings.base_path)
