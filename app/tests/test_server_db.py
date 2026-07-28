"""Smoke test for server db module."""

from server import db as server_db


def test_get_redis_is_exposed() -> None:
    assert callable(server_db.get_redis)
