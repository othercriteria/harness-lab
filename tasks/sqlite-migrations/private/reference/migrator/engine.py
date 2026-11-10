from .discovery import validate_migrations
from .planner import LEDGER_SQL, plan
from .sql import split_sql


def apply(connection, migrations, target=None):
    if connection.in_transaction:
        raise ValueError("caller already has an active transaction")
    migrations = validate_migrations(migrations)
    planned = plan(connection, migrations, target)
    pending = [m for m in migrations if m.version in planned["pending"]]
    if not pending:
        return {"applied": [], "current": planned["target"]}
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(LEDGER_SQL)
        for migration in pending:
            for statement in split_sql(migration.sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version,name,checksum) VALUES (?,?,?)",
                (migration.version, migration.name, migration.checksum),
            )
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    return {"applied": [m.version for m in pending], "current": planned["target"]}
