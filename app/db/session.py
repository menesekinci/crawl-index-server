from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings


def create_db_engine(settings: Settings):
    return create_engine(settings.database_url, echo=False, connect_args={"check_same_thread": False})


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine):
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

