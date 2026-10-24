import os
import subprocess
import sys

import sqlalchemy as sa
from sqlalchemy import create_engine

import heroku_alembic_bootstrap as bootstrap


def test_heroku_postgres_url_uses_installed_driver():
    env = {**os.environ, "DATABASE_URL": "postgres://u:p@localhost:5432/db"}
    code = "import database; print(database.engine.dialect.driver)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "psycopg2"


def _create_table(engine, name):
    metadata = sa.MetaData()
    sa.Table(name, metadata, sa.Column("id", sa.Integer, primary_key=True)).create(
        bind=engine
    )


def test_bootstrap_empty_database_runs_upgrade_only(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    calls = []
    monkeypatch.setattr(
        bootstrap,
        "run_alembic",
        lambda args: calls.append(args),
    )

    bootstrap.bootstrap_database(engine=engine)

    assert calls == [["upgrade", "head"]]


def test_bootstrap_legacy_database_stamps_then_upgrades(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    for table in bootstrap.BASELINE_TABLES:
        _create_table(engine, table)
    calls = []
    monkeypatch.setattr(
        bootstrap,
        "run_alembic",
        lambda args: calls.append(args),
    )

    bootstrap.bootstrap_database(engine=engine)

    assert calls == [["stamp", "8dd6ce7658ec"], ["upgrade", "head"]]


def test_bootstrap_initialized_database_runs_upgrade_only(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('8dd6ce7658ec')"
        )
    calls = []
    monkeypatch.setattr(
        bootstrap,
        "run_alembic",
        lambda args: calls.append(args),
    )

    bootstrap.bootstrap_database(engine=engine)

    assert calls == [["upgrade", "head"]]


def test_bootstrap_alembic_version_without_row_fails_safely(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
    calls = []
    monkeypatch.setattr(
        bootstrap,
        "run_alembic",
        lambda args: calls.append(args),
    )

    try:
        bootstrap.bootstrap_database(engine=engine)
        raise AssertionError("Expected RuntimeError for empty alembic_version table")
    except RuntimeError as error:
        assert "no valid revision record" in str(error)

    assert calls == []


def test_bootstrap_partial_database_fails_safely(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    _create_table(engine, "users")
    _create_table(engine, "companies")
    calls = []
    monkeypatch.setattr(
        bootstrap,
        "run_alembic",
        lambda args: calls.append(args),
    )

    try:
        bootstrap.bootstrap_database(engine=engine)
        raise AssertionError("Expected RuntimeError for partial baseline")
    except RuntimeError as error:
        assert "partial ZamLine baseline" in str(error)

    assert calls == []
