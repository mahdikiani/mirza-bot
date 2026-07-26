"""Focused message-orchestration handlers (menu, contact, messages, inline)."""

from apps.bots.common.handlers.contact import handle_contact_event
from apps.bots.common.handlers.inline import handle_inline_query_event
from apps.bots.common.handlers.messages import handle_message_event

__all__ = [
    "handle_contact_event",
    "handle_inline_query_event",
    "handle_message_event",
]
