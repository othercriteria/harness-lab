# Entering the shell does not install packages or change services.
export LOCAL_HARNESS_ROOT="${LOCAL_HARNESS_ROOT:-/bulk/dlk/local-harness}"
export LOCAL_HARNESS_RUNS="$LOCAL_HARNESS_ROOT/runs"
export UV_CACHE_DIR="$LOCAL_HARNESS_ROOT/cache/uv"
export BIG_MODELS_ROOT="${BIG_MODELS_ROOT:-/bulk/dlk/big-local-models}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export TOKENIZERS_PARALLELISM=false
unset PYTHONPATH PYTHONHOME
