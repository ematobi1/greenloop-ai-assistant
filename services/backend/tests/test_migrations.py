from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_upgrade_head_on_fresh_database(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"

    command.upgrade(alembic_config(database_url), "head")

    with create_engine(database_url).connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0001"


def test_downgrade_to_base(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'down.db').as_posix()}"
    config = alembic_config(database_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with create_engine(database_url).connect() as connection:
        rows = connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one()
    assert rows == 0
