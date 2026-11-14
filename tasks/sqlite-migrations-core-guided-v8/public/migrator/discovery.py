import hashlib
import re
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


_NAME = re.compile(r"([0-9]{4})_[a-z][a-z0-9_]*\.sql")


def validate_migrations(migrations):
    if not isinstance(migrations, list):
        raise ValueError("migrations must be a list")
    seen = set()
    for migration in migrations:
        if not isinstance(migration, Migration):
            raise ValueError("every migration must be a Migration")
        version = migration.version
        if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 9999:
            raise ValueError("invalid migration version")
        if not isinstance(migration.name, str):
            raise ValueError("invalid migration name")
        match = _NAME.fullmatch(migration.name)
        if match is None or int(match.group(1)) != version:
            raise ValueError("migration name must match its version")
        if not isinstance(migration.sql, str) or not migration.sql.strip() or "\0" in migration.sql:
            raise ValueError("migration SQL must be nonempty text without NUL")
        try:
            checksum = hashlib.sha256(migration.sql.encode("utf-8")).hexdigest()
        except UnicodeError as error:
            raise ValueError("migration SQL must be UTF-8 encodable") from error
        if not isinstance(migration.checksum, str) or migration.checksum != checksum:
            raise ValueError("migration checksum does not match SQL")
        if version in seen:
            raise ValueError("duplicate migration version")
        seen.add(version)
    return sorted(migrations, key=lambda migration: migration.version)


def discover(directory):
    root = Path(directory)
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError("migration root must be a non-symlink directory")
    result = []
    for path in root.iterdir():
        if not path.name.endswith(".sql"):
            continue
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("SQL migration must be a regular non-symlink file")
        match = _NAME.fullmatch(path.name)
        if match is None:
            raise ValueError("invalid migration filename: " + path.name)
        raw = path.read_bytes()
        result.append(Migration(int(match.group(1)), path.name, raw.decode("utf-8"),
                                hashlib.sha256(raw).hexdigest()))
    return validate_migrations(result)
