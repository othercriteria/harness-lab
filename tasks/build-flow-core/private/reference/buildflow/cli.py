import argparse
import json
import subprocess
import sys

from .planner import plan
from .runner import run
from .spec import load_spec
from .state import load_state, save_state


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("root")
    parser.add_argument("state")
    parser.add_argument("--target", action="append")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args(argv)
    try:
        spec, previous = load_spec(args.spec), load_state(args.state)
        if args.dry_run:
            result = {"plan": plan(spec, args.root, previous, args.target)}
            code = 0
        else:
            result = run(
                spec,
                args.root,
                lambda name, command: (
                    subprocess.run(
                        command, cwd=args.root, check=False, capture_output=True
                    ).returncode
                ),
                previous,
                args.target,
                args.keep_going,
            )
            save_state(args.state, result["state"])
            code = 1 if result["errors"] else 0
        print(json.dumps(result, sort_keys=True))
        return code
    except (ValueError, OSError) as error:
        print(str(error) or type(error).__name__, file=sys.stderr)
        return 2
