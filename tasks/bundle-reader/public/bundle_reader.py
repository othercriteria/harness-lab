"""Bounded ZIP inspection and extraction."""
from dataclasses import dataclass
from pathlib import Path


class BundleError(ValueError):
    pass


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BundleInfo:
    files: tuple[FileRecord, ...]
    directories: tuple[str, ...]
    total_bytes: int


def inspect_bundle(data: bytes, *, max_files: int = 128,
                   max_file_bytes: int = 1048576,
                   max_total_bytes: int = 4194304) -> BundleInfo:
    raise NotImplementedError


def extract_bundle(data: bytes, destination: Path | str, *, max_files: int = 128,
                   max_file_bytes: int = 1048576,
                   max_total_bytes: int = 4194304) -> BundleInfo:
    raise NotImplementedError
