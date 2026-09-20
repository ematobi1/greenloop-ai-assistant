import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import Base
from tests.migration_helpers import alembic_config

CORE_TABLES = {"settings", "conversations", "messages", "approvals", "audit_events"}
NEW_CONVERSATION_COLUMNS = {"owner", "provider", "model", "instructions"}
NEW_MESSAGE_COLUMNS = {"sequence", "status", "provider", "model"}


def database_url(tmp_path, name: str) -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_upgrade_head_on_fresh_database(tmp_path):
    url = database_url(tmp_path, "fresh.db")

    command.upgrade(alembic_config(url), "head")

    engine = create_engine(url)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0003"
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


def columns_of(url: str, table: str) -> set[str]:
    return {column["name"] for column in inspect(create_engine(url)).get_columns(table)}


def test_head_adds_owner_and_ordering_columns(tmp_path):
    url = database_url(tmp_path, "cols.db")

    command.upgrade(alembic_config(url), "head")

    assert NEW_CONVERSATION_COLUMNS <= columns_of(url, "conversations")
    assert NEW_MESSAGE_COLUMNS <= columns_of(url, "messages")


def test_downgrade_to_0002_removes_only_the_new_columns(tmp_path):
    url = database_url(tmp_path, "d2.db")
    config = alembic_config(url)
    command.upgrade(config, "head")

    command.downgrade(config, "0002")

    assert not NEW_CONVERSATION_COLUMNS & columns_of(url, "conversations")
    assert not NEW_MESSAGE_COLUMNS & columns_of(url, "messages")
    assert CORE_TABLES <= set(inspect(create_engine(url)).get_table_names())


def test_upgrade_backfills_owner_and_message_sequence(tmp_path):
    url = database_url(tmp_path, "backfill.db")
    config = alembic_config(url)
    command.upgrade(config, "0002")
    stamp = "2026-01-01 00:00:00"
    with create_engine(url).begin() as connection:
        for conversation_id in ("c1", "c2"):
            connection.execute(
                text(
                    "INSERT INTO conversations (id, title, created_at, updated_at)"
                    f" VALUES ('{conversation_id}', 't', '{stamp}', '{stamp}')"
                )
            )
        for message_id, conversation_id, created in [
            ("m3", "c1", "2026-01-01 00:00:03"),
            ("m1", "c1", "2026-01-01 00:00:01"),
            ("m2", "c1", "2026-01-01 00:00:02"),
            ("n1", "c2", "2026-01-01 00:00:09"),
        ]:
            connection.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content, created_at, updated_at)"
                    f" VALUES ('{message_id}', '{conversation_id}', 'user', 'x', '{created}', '{created}')"
                )
            )

    command.upgrade(config, "head")

    with create_engine(url).connect() as connection:
        sequences = dict(connection.execute(text("SELECT id, sequence FROM messages")).all())
        owners = {row[0] for row in connection.execute(text("SELECT owner FROM conversations"))}
        statuses = {row[0] for row in connection.execute(text("SELECT status FROM messages"))}
    assert sequences == {"m1": 1, "m2": 2, "m3": 3, "n1": 1}
    assert owners == {"local"}
    assert statuses == {"complete"}


def test_message_sequence_is_unique_per_conversation(tmp_path):
    url = database_url(tmp_path, "uq.db")
    command.upgrade(alembic_config(url), "head")
    stamp = "2026-01-01 00:00:00"
    insert = (
        "INSERT INTO messages (id, conversation_id, sequence, role, content, status, created_at, updated_at)"
        " VALUES ('{id}', 'c1', 1, 'user', 'x', 'complete', '{s}', '{s}')"
    )
    with create_engine(url).begin() as connection:
        connection.execute(
            text(f"INSERT INTO conversations (id, owner, title, created_at, updated_at) VALUES ('c1', 'local', 't', '{stamp}', '{stamp}')")
        )
        connection.execute(text(insert.format(id="a", s=stamp)))

    with pytest.raises(IntegrityError), create_engine(url).begin() as connection:
        connection.execute(text(insert.format(id="b", s=stamp)))


def test_message_status_check_constraint_rejects_bad_values(tmp_path):
    url = database_url(tmp_path, "status.db")
    command.upgrade(alembic_config(url), "head")
    stamp = "2026-01-01 00:00:00"
    with create_engine(url).begin() as connection:
        connection.execute(
            text(f"INSERT INTO conversations (id, owner, title, created_at, updated_at) VALUES ('c1', 'local', 't', '{stamp}', '{stamp}')")
        )

    with pytest.raises(IntegrityError, match="CHECK"), create_engine(url).begin() as connection:
        connection.execute(
            text(
                "INSERT INTO messages (id, conversation_id, sequence, role, content, status, created_at, updated_at)"
                f" VALUES ('a', 'c1', 1, 'user', 'x', 'bogus', '{stamp}', '{stamp}')"
            )
        )


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
