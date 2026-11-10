import argparse
import json
import sqlite3
import sys

from .discovery import discover
from .engine import apply
from .planner import plan


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("database")
    parser.add_argument("--target", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    connection = None
    try:
        migrations = discover(args.directory)
        connection = sqlite3.connect(args.database)
        result = (plan if args.dry_run else apply)(connection, migrations, args.target)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(str(error) or type(error).__name__, file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            connection.close()
