import json
from pathlib import Path


def load():
    root = Path(__file__).parent / "config"
    return tuple(json.loads((root / name).read_text()) for name in
                 ("workers.json", "compute.json", "storage.json"))
