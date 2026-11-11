from .planner import plan


def apply(connection, migrations, target=None):
    migrations = list(migrations)
    planned = plan(connection, migrations, target)
    for migration in migrations:
        if migration.version in planned["pending"]:
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, ?)",
                (migration.version, migration.name, migration.checksum),
            )
            connection.commit()
    return {"applied": planned["pending"], "current": planned["target"]}
