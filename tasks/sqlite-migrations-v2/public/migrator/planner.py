from .discovery import validate_migrations

LEDGER_SQL = "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL)"


def plan(connection, migrations, target=None):
    migrations = validate_migrations(migrations)
    connection.execute(LEDGER_SQL)
    connection.commit()
    applied = [
        row[0]
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]
    chosen = (
        migrations if target is None else [m for m in migrations if m.version <= target]
    )
    return {
        "applied": applied,
        "pending": [m.version for m in chosen if m.version not in applied],
        "target": max((m.version for m in chosen), default=0),
    }
