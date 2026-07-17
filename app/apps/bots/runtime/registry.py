"""Explicit bot registry — no BaseBot subclass discovery."""

from __future__ import annotations

_bots_by_name: dict[str, object] = {}
_bots_by_route: dict[str, object] = {}


def register(bot: object) -> None:
    """Register a bot instance by username and webhook route."""
    name = getattr(bot, "me", None)
    if not name:
        raise ValueError("bot.me is required for registry")
    _bots_by_name[str(name)] = bot
    route = getattr(bot, "webhook_route", None) or name
    _bots_by_route[str(route)] = bot


def get_by_name(bot_name: str) -> object:
    """Look up a bot instance by its username."""
    bot = _bots_by_name.get(bot_name)
    if bot is None:
        raise ValueError(f"bot not found by name: {bot_name}")
    return bot


def get_by_route(bot_route: str) -> object:
    """Look up a bot instance by its webhook route."""
    bot = _bots_by_route.get(bot_route)
    if bot is None:
        raise ValueError(f"bot not found by route: {bot_route}")
    return bot


def all_bots() -> list[object]:
    """Return all registered bot instances."""
    return list(_bots_by_name.values())


def clear() -> None:
    """Clear the registry (tests only)."""
    _bots_by_name.clear()
    _bots_by_route.clear()
