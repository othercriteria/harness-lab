"""Private structural check. Runtime rendering is verified separately."""

import json
from hashlib import sha256
from pathlib import Path

inputs = json.loads(Path("/evaluation/snapshot/snapshot.json").read_text())["contract"][
    "inputs"
]
for name, original in inputs.items():
    data = (Path("/workspace") / name).read_bytes()
    if not data.strip() or sha256(data).hexdigest() == original:
        raise SystemExit(f"Expected a nonempty edit to {name}")
print("Both requested files changed.")
