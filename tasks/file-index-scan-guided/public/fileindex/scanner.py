import hashlib
from pathlib import Path


def scan_tree(root, previous=None):
    root = Path(root)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            st = path.stat()
            files[path.relative_to(root).as_posix()] = {
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    return {"version": 1, "files": files}
