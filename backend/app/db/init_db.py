from app.db.base import Base
from app.db.session import engine
from app.models.generation_job import GenerationJob


def init_db() -> None:
    _ = GenerationJob
    Base.metadata.create_all(bind=engine)
