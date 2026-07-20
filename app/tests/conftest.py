import logging
import os
from collections.abc import AsyncGenerator, Generator

# Tests should not connect to the Docker-only Redis hostname from local runs.
os.environ.setdefault("REDIS_URI", "")
# Empty webhook key disables auth in tests unless explicitly configured.
os.environ.setdefault("WEBHOOK_API_KEY", "")

import httpx
import pytest
import pytest_asyncio
from beanie import init_beanie
from fastapi_mongo_base import models as base_mongo_models
from fastapi_mongo_base.utils.basic import get_all_subclasses

from server.config import Settings
from server.server import app as fastapi_app


@pytest.fixture(scope="session")
def setup_debugpy() -> None:
    if os.getenv("DEBUGPY", "False").lower() in ("true", "1", "yes"):
        import debugpy  # noqa: T100

        debugpy.listen(("127.0.0.1", 3020))  # noqa: T100
        logging.info("Waiting for debugpy client")
        debugpy.wait_for_client()  # noqa: T100


@pytest.fixture(scope="session")
def mongo_client() -> Generator[object]:
    from mongomock_motor import AsyncMongoMockClient

    mongo_client: AsyncMongoMockClient = AsyncMongoMockClient()
    yield mongo_client


# Async setup function to initialize the database with Beanie
async def init_db(mongo_client: object) -> None:
    database = mongo_client.get_database("test_db")

    # Patch mongomock Database.list_collection_names to accept extra kwargs
    # from newer beanie versions (authorizedCollections, nameOnly).
    import mongomock

    orig = mongomock.Database.list_collection_names

    def _compat_list(self: object, *args: object, **kwargs: object) -> list[str]:
        kwargs.pop("authorizedCollections", None)
        kwargs.pop("nameOnly", None)
        return orig(self, *args, **kwargs)

    mongomock.Database.list_collection_names = _compat_list

    await init_beanie(
        database=database,
        document_models=get_all_subclasses(base_mongo_models.BaseEntity),
    )


@pytest_asyncio.fixture(scope="session")
async def db(mongo_client: object) -> AsyncGenerator[None]:
    Settings.config_logger()
    logging.info("Initializing database")
    await init_db(mongo_client)
    logging.info("Database initialized")
    yield
    logging.info("Cleaning up database")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        for fixture_name in ("setup_debugpy", "db"):
            if fixture_name not in item.fixturenames:
                item.fixturenames.append(fixture_name)


@pytest_asyncio.fixture(scope="session")
async def client() -> AsyncGenerator[httpx.AsyncClient]:
    """Fixture to provide an AsyncClient for FastAPI app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url=f"https://test.uln.me{Settings.base_path}",
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="session")
async def authenticated_client(
    client: httpx.AsyncClient,
) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url=client.base_url,
        headers={"x-api-key": os.getenv("API_KEY") or ""},
    ) as ac:
        yield ac
