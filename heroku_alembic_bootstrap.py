import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

from database import database_url

BASELINE_TABLES = {
    "users",
    "companies",
    "trucks",
    "shipments",
    "shipment_matches",
    "reservations",
    "audit_logs",
}
BASELINE_REVISION = "8dd6ce7658ec"


def run_alembic(arguments: list[str]) -> None:
    command = ["alembic", *arguments]
    result = subprocess.run(
        command,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(arguments)} failed with exit code {result.returncode}"
        )


def detect_database_state(engine) -> str:
    tables = set(inspect(engine).get_table_names())

    if "alembic_version" in tables:
        with engine.connect() as connection:
            version = connection.execute(
                text(
                    "SELECT version_num FROM alembic_version "
                    "WHERE version_num IS NOT NULL AND TRIM(version_num) != ''"
                )
            ).scalar()
        if version:
            return "initialized"
        raise RuntimeError(
            "Database has an alembic_version table but no valid revision record; "
            "migration state is incomplete."
        )

    present = BASELINE_TABLES & tables
    if not present:
        return "empty"
    if present != BASELINE_TABLES:
        return "partial"
    return "legacy"


def bootstrap_database(engine=None, runner=None) -> None:
    runner = runner or run_alembic
    engine = engine or create_engine(database_url, pool_pre_ping=True)

    state = detect_database_state(engine)

    if state == "initialized":
        runner(["upgrade", "head"])
        return

    if state == "legacy":
        runner(["stamp", BASELINE_REVISION])
        runner(["upgrade", "head"])
        return

    if state == "empty":
        runner(["upgrade", "head"])
        return

    raise RuntimeError(
        "Database has a partial ZamLine baseline schema; "
        "expected all baseline application tables before Alembic can continue."
    )


def main() -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        bootstrap_database(engine=engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
