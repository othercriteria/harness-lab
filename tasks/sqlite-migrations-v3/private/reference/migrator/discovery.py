import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


NAME = re.compile(r"([0-9]{4})_[a-z][a-z0-9_]*\.sql")


def validate_migrations(migrations):
    if not isinstance(migrations, list):
        raise ValueError("migrations must be a list")
    seen = set()
    result = []
    for migration in migrations:
        if not isinstance(migration, Migration):
            raise ValueError("invalid migration object")
        match = (
            NAME.fullmatch(migration.name) if isinstance(migration.name, str) else None
        )
        if (
            type(migration.version) is not int
            or not 1 <= migration.version <= 9999
            or not match
            or int(match[1]) != migration.version
            or migration.version in seen
        ):
            raise ValueError("invalid or duplicate migration version/name")
        if (
            not isinstance(migration.sql, str)
            or not migration.sql.strip()
            or "\x00" in migration.sql
        ):
            raise ValueError("invalid SQL text")
        digest = hashlib.sha256(migration.sql.encode("utf-8")).hexdigest()
        if migration.checksum != digest:
            raise ValueError("invalid migration checksum")
        seen.add(migration.version)
        result.append(migration)
    return sorted(result, key=lambda m: m.version)


def discover(directory):
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("migration directory must be a real directory")
    result = []
    for path in root.iterdir():
        if not path.name.endswith(".sql"):
            continue
        if path.is_symlink() or not path.is_file() or NAME.fullmatch(path.name) is None:
            raise ValueError("invalid migration file")
        raw = path.read_bytes()
        result.append(
            Migration(
                int(path.name[:4]),
                path.name,
                raw.decode("utf-8"),
                hashlib.sha256(raw).hexdigest(),
            )
        )
    return validate_migrations(result)
