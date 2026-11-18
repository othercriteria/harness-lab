import argparse
import json

from .importer import import_events
from .store import EventStore


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    parser.add_argument("source")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    store = EventStore(args.database)
    try:
        with open(args.source, encoding="utf-8") as stream:
            print(json.dumps(import_events(stream, store, strict=args.strict)))
    finally:
        store.close()
    return 0
