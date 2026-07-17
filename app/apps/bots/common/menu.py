"""Main menu label → action mapping."""

from __future__ import annotations

from utils.i18n import button

MENU_ACTIONS: dict[str, str] = {
    button("help"): "help",
    button("my_account"): "account",
    button("buy_credits"): "purchase",
    button("balance"): "balance",
    button("settings"): "settings",
    "راهنما": "help",
    "حساب من": "account",
    "خرید اعتبار": "purchase",
    "موجودی": "balance",
    "⚙️ تنظیمات": "settings",
    "⚙️ Settings": "settings",
    "/help": "help",
    "/balance": "balance",
    "/purchase": "purchase",
    "/menu": "menu",
    "/settings": "settings",
}


def resolve_menu_action(text_value: str) -> str | None:
    """Map a reply-keyboard label or command to a menu action key."""
    stripped = text_value.strip()
    if not stripped:
        return None
    if stripped in MENU_ACTIONS:
        return MENU_ACTIONS[stripped]
    for label, action in MENU_ACTIONS.items():
        if stripped == label or stripped.startswith(f"{label} "):
            return action
    return None
