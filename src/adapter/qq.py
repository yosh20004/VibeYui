from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import nonebot
from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    Adapter as OneBotV11Adapter,
)
from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent


@dataclass(slots=True)
class QQActivity:
    group_id: int
    user_id: int
    user_name: str
    message: str
    to_me: bool


def init_nonebot() -> None:
    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)


def to_activity(event: GroupMessageEvent) -> QQActivity:
    sender = getattr(event, "sender", None)
    card = getattr(sender, "card", "") if sender is not None else ""
    nickname = getattr(sender, "nickname", "") if sender is not None else ""
    user_name = str(card or nickname or event.user_id)

    return QQActivity(
        group_id=int(event.group_id),
        user_id=int(event.user_id),
        user_name=user_name,
        message=event.get_plaintext().strip(),
        to_me=bool(getattr(event, "to_me", False)),
    )


def on_group_activity(
    handler: Callable[[QQActivity], Awaitable[None] | None],
    *,
    priority: int = 10,
    block: bool = False,
) -> None:
    matcher = on_message(priority=priority, block=block)

    @matcher.handle()
    async def _handle(bot: Bot, event: Event) -> None:
        if not isinstance(event, GroupMessageEvent):
            return
        if str(event.user_id) == str(bot.self_id):
            return

        activity = to_activity(event)
        if not activity.message:
            return

        result = handler(activity)
        if result is not None:
            await result
