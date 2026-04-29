from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.session import engine
from app.models.generation_job import GenerationJob


def init_db() -> None:
    _ = GenerationJob
    Base.metadata.create_all(bind=engine)
    _ensure_generation_job_columns()


def _ensure_generation_job_columns() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("generation_jobs")}
    missing_columns = {
        "size": "ALTER TABLE generation_jobs ADD COLUMN size VARCHAR(32) DEFAULT 'auto'",
        "aspect_ratio": "ALTER TABLE generation_jobs ADD COLUMN aspect_ratio VARCHAR(16) DEFAULT 'auto'",
        "reference_image_key": "ALTER TABLE generation_jobs ADD COLUMN reference_image_key VARCHAR(512)",
        "reference_image_content_type": "ALTER TABLE generation_jobs ADD COLUMN reference_image_content_type VARCHAR(128)",
        "reference_image_filename": "ALTER TABLE generation_jobs ADD COLUMN reference_image_filename VARCHAR(255)",
    }

    with engine.begin() as connection:
        for column, ddl in missing_columns.items():
            if column not in columns:
                connection.execute(text(ddl))
        connection.execute(
            text(
                """
                UPDATE generation_jobs
                SET size = CASE aspect_ratio
                    WHEN '1:1' THEN '1024x1024'
                    WHEN '3:4' THEN '1024x1536'
                    WHEN '9:16' THEN '1024x1792'
                    WHEN '4:3' THEN '1536x1024'
                    WHEN '16:9' THEN '1792x1024'
                    ELSE size
                END
                WHERE size = 'auto' AND aspect_ratio IS NOT NULL AND aspect_ratio != 'auto'
                """
            )
        )
