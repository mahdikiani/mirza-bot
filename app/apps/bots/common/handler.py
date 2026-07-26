"""
Platform-agnostic bot orchestration.

Adapters normalize updates into events and call this module.
Implementation lives in ``handlers/``; this module re-exports public entrypoints.
"""

from __future__ import annotations

from apps.bots.common.callbacks import handle_callback_event
from apps.bots.common.handler_context import BotRuntimeContext, EventRenderer
from apps.bots.common.handlers import (
    handle_contact_event,
    handle_inline_query_event,
    handle_message_event,
)

__all__ = [
    "BotRuntimeContext",
    "EventRenderer",
    "handle_callback_event",
    "handle_contact_event",
    "handle_inline_query_event",
    "handle_message_event",
]
