"""Public application version behavior."""

from apps.bots.common.menu import resolve_menu_action
from utils.version import app_version


def test_installed_version_matches_release() -> None:
    assert app_version() == "0.1.38"


def test_version_command_is_routable() -> None:
    assert resolve_menu_action("/version") == "version"
