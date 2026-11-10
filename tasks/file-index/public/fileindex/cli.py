import argparse
import json

from .catalog import diff_catalogs, load_catalog, save_catalog
from .scanner import scan_tree


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("catalog")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    old = load_catalog(args.catalog)
    new = scan_tree(args.root, old)
    diff = diff_catalogs(old, new)
    save_catalog(args.catalog, new)
    print(json.dumps(diff))
    return 0
