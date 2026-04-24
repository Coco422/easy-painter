from app.db.base import Base
from app.db.session import engine
from app.models.generation_job import GenerationJob
from sqlalchemy import inspect, text


def init_db() -> None:
    _ = GenerationJob
    Base.metadata.create_all(bind=engine)
    _ensure_generation_job_columns()


def _ensure_generation_job_columns() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("generation_jobs")}
    if "aspect_ratio" in columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE generation_jobs ADD COLUMN aspect_ratio VARCHAR(16) DEFAULT 'auto'"))
