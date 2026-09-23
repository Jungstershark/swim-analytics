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
    assert {"sessionId", "resultStatus", "isExhibition"} <= result_columns
    result_column_metadata = {
        column["name"]: column for column in schema.get_columns("Result")
    }
    assert result_column_metadata["isExhibition"]["nullable"] is False
    relay_columns = {column["name"] for column in schema.get_columns("RelayResult")}
    assert {"sessionId", "legParseStatus", "legParseWarning", "resultStatus"} <= relay_columns
    source_event_columns = {column["name"] for column in schema.get_columns("SourceEvent")}
    assert "manifestSha256" in source_event_columns
    edition_columns = {column["name"] for column in schema.get_columns("CompetitionEdition")}
    assert {"sourceManifestSha256", "sourceManifestCaptureKind", "sourceManifestCapturedAt"} <= edition_columns
    assert "CompetitionEdition_sourceEvent_uq" in {
        index["name"] for index in schema.get_indexes("CompetitionEdition") if index["unique"]
    }
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


def test_individual_exhibition_migration_backfills_and_downgrades(tmp_path: Path):
    database_path = tmp_path / "pre-exhibition.db"
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

    alembic("upgrade", "f6a7b8c9d0e1")
    engine = create_engine(env["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO "Swimmer" (name) VALUES (\'Legacy Athlete\')'))
        connection.execute(text('INSERT INTO "Meet" (name, date) VALUES (\'Legacy Meet\', \'2026-01-01\')'))
        connection.execute(text(
            'INSERT INTO "Result" '
            '("swimmerId", "meetId", event, time, "isDQ", "resultStatus") '
            "VALUES (1, 1, '50 Freestyle', '24.00', 0, 'finished')"
        ))

    alembic("upgrade", "head")
    schema = inspect(engine)
    column = next(
        item for item in schema.get_columns("Result") if item["name"] == "isExhibition"
    )
    assert column["nullable"] is False
    with engine.begin() as connection:
        assert connection.execute(
            text('SELECT "isExhibition" FROM "Result" WHERE id = 1')
        ).scalar_one() in {False, 0}
        connection.execute(text(
            'INSERT INTO "Result" '
            '("swimmerId", "meetId", event, time, "isDQ", "resultStatus") '
            "VALUES (1, 1, '100 Freestyle', '53.00', 0, 'finished')"
        ))
        assert connection.execute(
            text('SELECT "isExhibition" FROM "Result" WHERE id = 2')
        ).scalar_one() in {False, 0}

    alembic("downgrade", "f6a7b8c9d0e1")
    assert "isExhibition" not in {
        item["name"] for item in inspect(engine).get_columns("Result")
    }


def test_optional_numbering_migration_downgrades_with_distinct_backfill(tmp_path: Path):
    """Every unnumbered row must get its *own* provisional number.

    A single correlated UPDATE would hand the same value to all NULL sessions in
    a day and then trip the partial unique index that is still in place when the
    downgrade runs.
    """
    database_path = tmp_path / "unnumbered.db"
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

    alembic("upgrade", "head")
    engine = create_engine(env["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text(
            'INSERT INTO "CompetitionDay" '
            '("competitionSegmentId", "dayNumber", "date", "resolutionStatus", '
            '"resolverVersion", "resolvedAt") '
            "VALUES (1, NULL, '2026-06-01', 'derived', 'v1', '2026-06-03')"
        ))
        for sha in ("a", "b", "c"):
            connection.execute(text(
                'INSERT INTO "CompetitionSession" '
                '("competitionDayId", "sessionNumber", "sourceDocumentSha", '
                '"resolutionStatus", "resolverVersion", "resolvedAt") '
                f"VALUES (1, NULL, '{sha * 64}', 'derived', 'v1', '2026-06-03')"
            ))

    alembic("downgrade", "07b8c9d0e1f2")
    with engine.connect() as connection:
        session_numbers = connection.execute(
            text('SELECT "sessionNumber" FROM "CompetitionSession" ORDER BY id')
        ).scalars().all()
        assert sorted(session_numbers) == [1, 2, 3]
        day_numbers = connection.execute(
            text('SELECT "dayNumber" FROM "CompetitionDay" ORDER BY id')
        ).scalars().all()
        assert day_numbers == [1]

    alembic("upgrade", "head")
    session_columns = {
        column["name"] for column in inspect(engine).get_columns("CompetitionSession")
    }
    assert {"sourceDocumentSha", "sourceEvidenceKey"} <= session_columns
