import logging
import re
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from config import DB_URL

logger = logging.getLogger(__name__)

# Base class for all models
Base = declarative_base()


def _prepare_asyncpg_url(db_url: str) -> tuple[str, dict]:
    """
    asyncpg does not accept libpq parameters like 'sslmode' or 'channel_binding'.
    Strip them from the URL and map SSL requirement to asyncpg's native connect_arg.
    This only applies to the asyncpg runtime engine; Alembic uses psycopg2 separately.
    """
    requires_ssl = bool(
        re.search(r'[?&]sslmode=require', db_url)
        or re.search(r'[?&]ssl=require', db_url)
    )
    clean_url = re.sub(r'[?&]sslmode=[^&]*', '', db_url)
    clean_url = re.sub(r'[?&]channel_binding=[^&]*', '', clean_url)
    clean_url = re.sub(r'[?&]ssl=[^&]*', '', clean_url)
    clean_url = re.sub(r'\?&', '?', clean_url)
    clean_url = clean_url.rstrip('?').rstrip('&')
    connect_args = {"ssl": True} if requires_ssl else {}
    return clean_url, connect_args


_asyncpg_url, _connect_args = _prepare_asyncpg_url(DB_URL)

# Create an async engine for the database
async_engine = create_async_engine(
    _asyncpg_url,
    pool_pre_ping=True,
    connect_args=_connect_args,
    echo=False
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def init_db():
    """Initialize database tables (use Alembic migrations instead)"""
    logger.info("Initializing database...")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")

@asynccontextmanager
async def get_db():
    """Dependency function to get a database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def close_db():
    """Close all database connections"""
    await async_engine.dispose()
    logger.info("Database connections closed")
