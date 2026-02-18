from __future__ import annotations

import nonebot
from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    Adapter as OneBotV11Adapter,
)
from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent

from src.adapter import to_activity
from src.config import ConfigManager


def build_app() -> None:
    config = ConfigManager()
    workflow = config.build_message_workflow()

    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)

    matcher = on_message(priority=10, block=False)

    @matcher.handle()
    async def _handle(bot: Bot, event: Event) -> None:
        if not isinstance(event, GroupMessageEvent):
            return
        if str(event.user_id) == str(bot.self_id):
            return

        activity = to_activity(event)
        if not activity.message:
            return

        reply = workflow.process(
            activity.message,
            at_user=activity.to_me,
            source="qq_group",
            group_id=activity.group_id,
        )
        if reply:
            await bot.send(event, reply)


def main() -> None:
    build_app()
    nonebot.run()


if __name__ == "__main__":
    main()
