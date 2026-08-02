"""Static migration checks for source monitoring release safety.

These tests cover dialect-specific hazards that SQLite migration smoke tests may
not catch. In particular, PostgreSQL treats unquoted mixed-case identifiers as
lowercase, while SQLAlchemy/Alembic creates this schema with quoted mixed-case
names such as "SourceSite" and "baseUrl".
"""

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "d4b63ef2a9c0_add_source_monitoring_foundation.py"
)


def test_source_monitoring_seed_sql_quotes_postgres_mixed_case_identifiers():
    text = MIGRATION.read_text()

    assert 'INSERT INTO "SourceSite"' in text
    assert 'INSERT INTO "SourceRule"' in text
    assert 'FROM "SourceSite"' in text

    for identifier in [
        '"baseUrl"',
        '"adapterType"',
        '"isEnabled"',
        '"sourceSiteId"',
        '"indexUrl"',
        '"autoImportPolicy"',
    ]:
        assert identifier in text

    assert "INSERT INTO SourceSite" not in text
    assert "INSERT INTO SourceRule" not in text
    assert "FROM SourceSite" not in text
