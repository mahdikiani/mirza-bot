"""Inline keyboard callback handling — thin dispatcher over focused modules."""

from apps.bots.common.callbacks.content import get_content
from apps.bots.common.callbacks.content import get_content as _get_content
from apps.bots.common.callbacks.dispatcher import handle_callback_event

__all__ = [
    "_get_content",
    "get_content",
    "handle_callback_event",
]
