from fastapi import APIRouter, BackgroundTasks

from apps.bots.handlers import update_bot

router = APIRouter(prefix="/bots", tags=["Bots"])


@router.post("/webhook/{bot}")
async def bot_update(
    bot: str, data: dict[str, object], background_tasks: BackgroundTasks
) -> None:
    background_tasks.add_task(update_bot, bot, data)
