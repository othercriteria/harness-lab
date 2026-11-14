from .discovery import validate_migrations

LEDGER_SQL = "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL)"


def plan(connection, migrations, target=None):
    migrations = validate_migrations(migrations)
    versions = [migration.version for migration in migrations]
    if target is None:
        target = versions[-1] if versions else 0
    elif isinstance(target, bool) or not isinstance(target, int) or (target != 0 and target not in versions):
        raise ValueError("target must be zero or an available migration version")
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE",
        ("schema_migrations",),
    ).fetchone()
    rows = [] if exists is None else connection.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    expected = [(migration.version, migration.name, migration.checksum)
                for migration in migrations[:len(rows)]]
    if rows != expected:
        raise ValueError("applied migrations must exactly match the supplied prefix")
    applied = [row[0] for row in rows]
    if applied and target < applied[-1]:
        raise ValueError("migration downgrade is unsupported")
    return {"applied": applied,
            "pending": [migration.version for migration in migrations[len(rows):]
                        if migration.version <= target],
            "target": target}
