import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def discover(directory):
    result = []
    for path in sorted(Path(directory).glob("*.sql")):
        raw = path.read_bytes()
        result.append(
            Migration(
                int(path.name.split("_")[0]),
                path.name,
                raw.decode("utf-8"),
                hashlib.sha256(raw).hexdigest(),
            )
        )
    return result


def validate_migrations(migrations):
    return list(migrations)
