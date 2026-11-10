import argparse
import json
import sys

from .catalog import diff_catalogs, load_catalog, save_catalog
from .scanner import scan_tree


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("catalog")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        old = load_catalog(args.catalog)
        new = scan_tree(args.root, old)
        changes = diff_catalogs(old, new)
        if not args.dry_run:
            save_catalog(args.catalog, new)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(changes))
    return 0
