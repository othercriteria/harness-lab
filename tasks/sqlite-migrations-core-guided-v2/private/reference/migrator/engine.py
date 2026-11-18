from .planner import LEDGER_SQL, plan
from .sql import split_sql


def apply(connection, migrations, target=None):
    if connection.in_transaction:
        raise ValueError("cannot apply migrations inside a caller transaction")
    planned = plan(connection, migrations, target)
    if not planned["pending"]:
        return {"applied": [], "current": planned["target"]}
    by_version = {migration.version: migration for migration in migrations}
    try:
        connection.execute("BEGIN")
        connection.execute(LEDGER_SQL)
        for version in planned["pending"]:
            migration = by_version[version]
            for statement in split_sql(migration.sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.checksum),
            )
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            try:
                connection.execute("ROLLBACK")
            except BaseException:
                pass  # Preserve the original execution/commit exception.
        raise
    return {"applied": planned["pending"], "current": planned["target"]}
