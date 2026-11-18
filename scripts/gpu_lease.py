"""Current admission gate for trusted historical experiment launchers.

Use this entrypoint when replaying frozen wrappers that predate the delegated-job
recovery latch. It performs no service changes. Never expose it to local models.
"""

import os
import sys

from with_ollama_released import gpu_experiment_lock


def main(argv):
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv or os.environ.get("BIG_MODELS_GPU_LOCK_FD"):
        raise ValueError("Supply a command and acquire a fresh outer lease")
    with gpu_experiment_lock() as lease:
        os.set_inheritable(lease.fileno(), True)
        environment = os.environ | {"BIG_MODELS_GPU_LOCK_FD": str(lease.fileno())}
        os.execvpe(argv[0], argv, environment)


if __name__ == "__main__":
    main(sys.argv[1:])
