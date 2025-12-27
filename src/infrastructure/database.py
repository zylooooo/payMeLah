from config import DB_URL
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import logging

logger = logging.getLogger(__name__)

# Create engine, the connection pool for the database
engine = create_engine(
    DB_URL,
    pool_pre_ping=True, # Verify connections before using them
    pool_size=10, # Maximum number of connections in the pool
    max_overflow=20, # Additional connections to create when all connections are in use
    echo=False
)

# Session factory to create new session per request
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for all models
Base = declarative_base()

def get_db():
    """
    Dependency function to get a database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """
    Function to initialize the database once with the tables
    Call this once upon application startup
    """
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully")

def close_db():
    """Close all database connections"""
    engine.dispose()
    logger.info("Database connections closed")