import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import Base
from tests.migration_helpers import alembic_config

CORE_TABLES = {"settings", "conversations", "messages", "approvals", "audit_events"}


def database_url(tmp_path, name: str) -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_upgrade_head_on_fresh_database(tmp_path):
    url = database_url(tmp_path, "fresh.db")

    command.upgrade(alembic_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0002"
    assert CORE_TABLES <= set(inspect(engine).get_table_names())


def test_downgrade_to_baseline_removes_core_tables(tmp_path):
    url = database_url(tmp_path, "down.db")
    config = alembic_config(url)

    command.upgrade(config, "head")
    command.downgrade(config, "0001")

    engine = create_engine(url)
    assert not CORE_TABLES & set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0001"


def test_downgrade_to_base(tmp_path):
    url = database_url(tmp_path, "base.db")
    config = alembic_config(url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    with create_engine(url).connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one() == 0


def test_upgrade_is_repeatable_after_downgrade(tmp_path):
    url = database_url(tmp_path, "cycle.db")
    config = alembic_config(url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    assert CORE_TABLES <= set(inspect(create_engine(url)).get_table_names())


def test_migrations_match_models(tmp_path):
    url = database_url(tmp_path, "drift.db")
    command.upgrade(alembic_config(url), "head")

    with create_engine(url).connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_status_check_constraint_rejects_bad_values(tmp_path):
    url = database_url(tmp_path, "check.db")
    command.upgrade(alembic_config(url), "head")

    with pytest.raises(IntegrityError, match="CHECK"), create_engine(url).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO approvals"
                " (id, action, description, status, created_at, updated_at)"
                " VALUES ('a', 'x', '', 'bogus', '2026-01-01', '2026-01-01')"
            )
        )
