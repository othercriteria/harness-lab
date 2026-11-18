import argparse
import json
import sys
from contextlib import ExitStack

from .importer import ImportFailure, import_events
from .store import EventStore


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("source")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        with ExitStack() as stack:
            source = (
                sys.stdin
                if args.source == "-"
                else stack.enter_context(open(args.source, encoding="utf-8"))
            )
            store = EventStore(args.database)
            stack.callback(store.close)
            report = import_events(source, store, strict=args.strict)
        print(json.dumps(report))
        return 0
    except ImportFailure as error:
        print(
            json.dumps({"line": error.line, "message": error.message}), file=sys.stderr
        )
        return 2
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2
