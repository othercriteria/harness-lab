"""Check a portable example packet from the command line."""

import json
import sys
from pathlib import Path

from evidence_files import check_files


def main():
    results = check_files(Path(sys.argv[1]))
    report = {"ok": [], "missing": [], "changed": []}
    for name, status in results:
        report[status].append(name)
    print(json.dumps(report))
    sys.exit(0 if all(status == "ok" for _, status in results) else 1)


if __name__ == "__main__":
    main()
