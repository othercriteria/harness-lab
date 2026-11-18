import json
import sqlite3


class EventStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.commit()

    def insert(self, event):
        result = self.connection.execute(
            "INSERT OR IGNORE INTO events VALUES (?, ?)",
            (event["id"], json.dumps(event)),
        )
        return result.rowcount == 1

    def get(self, identifier):
        row = self.connection.execute(
            "SELECT payload FROM events WHERE id=?", (identifier,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def count(self):
        return self.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self):
        self.connection.close()
