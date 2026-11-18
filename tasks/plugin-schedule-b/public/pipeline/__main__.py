import argparse
import json
from .contracts import FEATURES, TARGETS
from .planner import plan

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=sorted(TARGETS))
    parser.add_argument("--feature", action="append", default=[], choices=sorted(FEATURES))
    args = parser.parse_args()
    print(json.dumps(plan(set(args.feature), args.target)))

if __name__ == "__main__":
    main()
