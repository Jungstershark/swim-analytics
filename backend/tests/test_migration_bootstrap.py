"""Executable migration bootstrap tests for rebuildable databases."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_empty_database_upgrades_to_competition_schema(tmp_path: Path):
    database_path = tmp_path / "fresh.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path}"

    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr

    schema = inspect(create_engine(env["DATABASE_URL"]))
    tables = set(schema.get_table_names())
    assert {
        "Swimmer",
        "Meet",
        "Result",
        "RelayResult",
        "RelayLeg",
        "CompetitionEdition",
        "CompetitionSegment",
        "CompetitionDay",
        "CompetitionSession",
    } <= tables
    result_columns = {column["name"] for column in schema.get_columns("Result")}
    assert {"sessionId", "resultStatus"} <= result_columns
    relay_columns = {column["name"] for column in schema.get_columns("RelayResult")}
    assert {"sessionId", "legParseStatus", "legParseWarning", "resultStatus"} <= relay_columns
    assert "RelayResult_leg_parse_status_ck" in {
        constraint["name"] for constraint in schema.get_check_constraints("RelayResult")
    }
    assert "Result_status_ck" in {
        constraint["name"] for constraint in schema.get_check_constraints("Result")
    }
    assert "RelayResult_status_ck" in {
        constraint["name"] for constraint in schema.get_check_constraints("RelayResult")
    }
    assert {index["name"] for index in schema.get_indexes("Result") if index["unique"]} == {
        "Result_contentHash_uq"
    }
    assert {index["name"] for index in schema.get_indexes("RelayResult") if index["unique"]} == {
        "RelayResult_contentHash_uq"
    }


def test_status_migration_backfills_legacy_rows_and_enforces_vocabulary(tmp_path: Path):
    database_path = tmp_path / "legacy.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path}"

    def alembic(*args: str) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    alembic("upgrade", "e5f6a7b8c9d0")
    engine = create_engine(env["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO "Swimmer" (name) VALUES (\'Legacy Athlete\')'))
        connection.execute(text('INSERT INTO "Meet" (name, date) VALUES (\'Legacy Meet\', \'2026-01-01\')'))
        connection.execute(text(
            'INSERT INTO "Result" ("swimmerId", "meetId", event, time, "isDQ") VALUES '
            "(1, 1, '50 Freestyle', '24.00', 0), "
            "(1, 1, '100 Freestyle', NULL, 1), "
            "(1, 1, '200 Freestyle', NULL, 0)"
        ))
        connection.execute(text(
            'INSERT INTO "RelayResult" ("meetId", event, "teamName", time, "isDQ") VALUES '
            "(1, '200 Freestyle Relay', 'Legacy Club', '1:40.00', 0), "
            "(1, '400 Freestyle Relay', 'Legacy Club', NULL, 1)"
        ))

    alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text('SELECT "resultStatus" FROM "Result" ORDER BY id')).scalars().all() == [
            "finished", "dq", "unknown"
        ]
        assert connection.execute(text('SELECT "resultStatus" FROM "RelayResult" ORDER BY id')).scalars().all() == [
            "finished", "dq"
        ]
        with pytest.raises(IntegrityError):
            connection.execute(text('UPDATE "Result" SET "resultStatus" = \'bogus\' WHERE id = 1'))
