from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from harness.storage.database import (
    SessionFactory,
    create_database,
    create_schema,
    drop_schema,
)

DatabaseFixture = tuple[AsyncEngine, SessionFactory]


@pytest_asyncio.fixture
async def database() -> AsyncIterator[DatabaseFixture]:
    engine, sessions = create_database(
        "postgresql+asyncpg://harness:harness@localhost:5432/harness"
    )
    await drop_schema(engine)
    await create_schema(engine)
    try:
        yield engine, sessions
    finally:
        await engine.dispose()
