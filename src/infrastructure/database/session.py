"""
Database session management with async SQLAlchemy.
Includes connection pooling, session lifecycle, and health checks.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
import structlog

from src.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.app_debug,
    pool_pre_ping=True,
    pool_recycle=3600,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


async def init_db():
    """Initialize database connection and verify connectivity."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected", url=settings.database_url.split("@")[-1])
    except Exception as e:
        logger.warning(
            "database_connection_failed",
            error=str(e),
            url=settings.database_url.split("@")[-1],
            hint="Server will start but DB-dependent endpoints will fail. Start PostgreSQL and retry.",
        )


async def close_db():
    """Close database engine."""
    try:
        await engine.dispose()
        logger.info("database_disconnected")
    except Exception:
        pass


async def get_db() -> AsyncSession:
    """Dependency injection for FastAPI routes."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
