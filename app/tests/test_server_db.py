"""Smoke test for server db re-export."""

from server import db as server_db


def test_db_reexport() -> None:
    assert server_db.db is not None
