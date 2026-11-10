from .discovery import validate_migrations

LEDGER_SQL = "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL)"


def plan(connection, migrations, target=None):
    migrations = validate_migrations(migrations)
    versions = [m.version for m in migrations]
    if target is None:
        target = max(versions, default=0)
    if (
        type(target) is not int
        or target < 0
        or (target != 0 and target not in versions)
    ):
        raise ValueError("invalid target")
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    rows = (
        list(
            connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            )
        )
        if exists
        else []
    )
    if len(rows) > len(migrations):
        raise ValueError("ledger has unknown migrations")
    for row, migration in zip(rows, migrations):
        if tuple(row) != (migration.version, migration.name, migration.checksum):
            raise ValueError("applied migration history has drifted")
    applied = [row[0] for row in rows]
    if applied and target < applied[-1]:
        raise ValueError("downgrade is not supported")
    return {
        "applied": applied,
        "pending": [v for v in versions[len(rows) :] if v <= target],
        "target": target,
    }
