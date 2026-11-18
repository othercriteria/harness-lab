import argparse
import json
from .allocator import allocate
from .loader import load


def main():
    workers, compute, storage = load()
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=workers["profiles"], required=True)
    parser.add_argument("services", nargs="*")
    args = parser.parse_args()
    if not set(args.services) <= set(compute):
        parser.error("unknown service")
    print(json.dumps(allocate(set(args.services), args.profile), sort_keys=True))


if __name__ == "__main__":
    main()
