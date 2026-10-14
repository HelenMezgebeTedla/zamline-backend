import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

database_url = os.getenv("DATABASE_URL", "sqlite:///./zamline.db")

if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql+psycopg2://",
        1,
    )
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace(
        "postgresql://",
        "postgresql+psycopg2://",
        1,
    )
elif database_url.startswith("postgresql+psycopg://"):
    database_url = database_url.replace(
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        1,
    )

connect_args = {}

if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
