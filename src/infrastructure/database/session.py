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


def get_engine():
    """Return the async SQLAlchemy engine (used by readiness checks)."""
    return engine


async def _create_tables():
    """
    Create all SQLAlchemy-defined tables that do not already exist.
    Importing models here (rather than at module level) avoids the circular
    import: models.py -> session.py (Base) -> models.py.
    """
    try:
        import src.infrastructure.database.models  # noqa: F401 — registers all models with Base.metadata
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database_tables_ensured")
    except Exception as e:
        logger.warning("database_table_creation_failed", error=str(e))


async def init_db():
    """Initialize database connection and verify connectivity, then ensure all tables exist."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected", url=settings.database_url.split("@")[-1])
        await _create_tables()
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
