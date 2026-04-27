import asyncio

from fastapi import APIRouter
from fastapi_mongo_base.core import app_factory

from apps.ai.routes import router as ai_router
from apps.ai.task_poller import run_task_poller
from apps.bots.handlers import BotHandler
from apps.bots.routes import router as bots_router
from server.redis import get_redis

from . import config

app = app_factory.create_app(
    settings=config.Settings(),
    init_functions=[
        get_redis,
        BotHandler().setup,
        lambda: asyncio.create_task(run_task_poller()),
    ],
)

server_router = APIRouter()

for router in [bots_router, ai_router]:
    server_router.include_router(router)

app.include_router(server_router, prefix=config.Settings.base_path)
