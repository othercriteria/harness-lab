"""Prospective v5 gate: existing CLI checks plus container-validation observations."""

import json

from grade_migrations import check as check_cli


def check(gate):
    check_cli(gate)
    marker = int(gate.token()[:6], 16)
    driver = b"""import hashlib, json, sqlite3, sys
sys.path.insert(0, "/workspace")
from migrator.discovery import Migration
from migrator.engine import apply
marker = json.load(open("probe/marker.json"))
sql = "CREATE TABLE changed(x);"
item = Migration(1, "0001_change.sql", sql, hashlib.sha256(sql.encode()).hexdigest())
observations = {}
for active in (False, True):
    for kind in ("tuple", "iterator", "mapping", "none"):
        connection = sqlite3.connect(":memory:")
        if active:
            connection.execute("CREATE TABLE keep(x)")
            connection.execute("INSERT INTO keep VALUES (?)", (marker,))
        containers = {"tuple": (item,), "iterator": iter([item]), "mapping": {1: item}, "none": None}
        statements = []
        connection.set_trace_callback(statements.append)
        error = None
        try:
            apply(connection, containers[kind])
        except Exception as exc:
            error = type(exc).__name__
        connection.set_trace_callback(None)
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        observations[kind + ("_active" if active else "_idle")] = {
            "error": error, "statements": statements, "active": connection.in_transaction,
            "tables": tables,
            "data": list(connection.execute("SELECT x FROM keep")) if active and "keep" in tables else [],
        }
        connection.close()
print(json.dumps(observations))
"""
    probe = gate.case(
        "migration_container_observations",
        {"probe/driver.py": driver, "probe/marker.json": json.dumps(marker).encode()},
        "python -I -S probe/driver.py",
    )
    try:
        observed = gate.json(probe)
    except (ValueError, TypeError):
        observed = None
    transport = (
        type(probe.result.get("returncode")) is int
        and probe.result["returncode"] == 0
        and probe.result.get("stopped_by") is None
        and not probe.result.get("stderr")
        and isinstance(observed, dict)
    )
    for active in (False, True):
        for kind in ("tuple", "iterator", "mapping", "none"):
            name = kind + ("_active" if active else "_idle")
            expected = {
                "error": "ValueError",
                "statements": [],
                "active": active,
                "tables": ["keep"] if active else [],
                "data": [[marker]] if active else [],
            }
            actual = observed.get(name) if isinstance(observed, dict) else None
            gate.record(
                "migration_container_" + name,
                transport
                and json.dumps(actual, sort_keys=True)
                == json.dumps(expected, sort_keys=True),
                {"actual": actual, "expected": expected, "transport": probe.result},
            )
