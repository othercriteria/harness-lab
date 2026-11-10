"""Bounded ZIP inspection and extraction."""
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import stat
import struct
import zipfile
import zlib


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


def _path(info):
    name = info.orig_filename
    directory = name.endswith("/")
    path = name[:-1] if directory else name
    parts = path.split("/")
    if (not path or "\\" in path or "\0" in path
            or any(p in ("", ".", "..") or ":" in p for p in parts)):
        raise BundleError("Invalid entry path")
    kind = stat.S_IFMT(info.external_attr >> 16)
    if kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG):
        raise BundleError("Unsupported or inconsistent entry type")
    return path, parts, directory


def _payload(data, archive, info, cap):
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise BundleError("Unsupported compression")
    if info.flag_bits & (1 | 64):
        raise BundleError("Encrypted entry")
    # Let ZipFile perform its local-header and overlap checks, without using
    # ZipExtFile's metadata-limited read as our payload-integrity check.
    with archive.open(info):
        pass
    name_len, extra_len = struct.unpack_from("<HH", data, info.header_offset + 26)
    start = info.header_offset + 30 + name_len + extra_len
    end = start + info.compress_size
    if start < 0 or end > len(data):
        raise BundleError("Truncated payload")
    chunks = []
    length = 0
    crc = 0
    decoder = (zlib.decompressobj(-15)
               if info.compress_type == zipfile.ZIP_DEFLATED else None)
    for offset in range(start, end, 65536):
        encoded = data[offset:min(offset + 65536, end)]
        chunk = decoder.decompress(encoded, cap - length + 1) if decoder else encoded
        length += len(chunk)
        if length > cap:
            raise BundleError("Uncompressed size exceeds limit")
        chunks.append(chunk)
        crc = zlib.crc32(chunk, crc)
        if decoder and (decoder.unused_data or decoder.unconsumed_tail):
            raise BundleError("Unused compressed bytes")
    if decoder and not decoder.eof:
        raise BundleError("Unfinished deflate stream")
    if length != info.file_size or crc != info.CRC:
        raise BundleError("Payload size or CRC mismatch")
    return b"".join(chunks)


def _validate(data, max_files, max_file_bytes, max_total_bytes):
    if type(data) is not bytes:
        raise BundleError("data must be bytes")
    for limit in (max_files, max_file_bytes, max_total_bytes):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise BundleError("Limits must be positive integers")
    contents = {}
    directories = set()
    explicit = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                path, parts, directory = _path(info)
                if path in explicit:
                    raise BundleError("Duplicate canonical path")
                explicit.add(path)
                for depth in range(1, len(parts)):
                    parent = "/".join(parts[:depth])
                    if parent in contents:
                        raise BundleError("File is an ancestor")
                    directories.add(parent)
                if directory:
                    if path in contents:
                        raise BundleError("File/directory collision")
                    directories.add(path)
                    _payload(data, archive, info, 0)
                else:
                    if path in directories:
                        raise BundleError("File/directory collision")
                    if len(contents) >= max_files:
                        raise BundleError("Too many files")
                    content = _payload(data, archive, info,
                                       min(max_file_bytes, max_total_bytes - total))
                    contents[path] = content
                    total += len(content)
    except BundleError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, UnicodeError,
            ValueError, EOFError, RuntimeError, NotImplementedError,
            struct.error, zlib.error, OverflowError) as exc:
        raise BundleError("Invalid or unsupported archive") from exc
    records = tuple(FileRecord(path, len(content), hashlib.sha256(content).hexdigest())
                    for path, content in sorted(contents.items()))
    return BundleInfo(records, tuple(sorted(directories)), total), contents


def inspect_bundle(data: bytes, *, max_files: int = 128,
                   max_file_bytes: int = 1048576,
                   max_total_bytes: int = 4194304) -> BundleInfo:
    return _validate(data, max_files, max_file_bytes, max_total_bytes)[0]


def extract_bundle(data: bytes, destination: Path | str, *, max_files: int = 128,
                   max_file_bytes: int = 1048576,
                   max_total_bytes: int = 4194304) -> BundleInfo:
    if not isinstance(destination, (Path, str)):
        raise BundleError("destination must be a Path or str")
    destination = Path(destination)
    if os.path.lexists(destination):
        raise BundleError("Destination already exists")
    result, contents = _validate(data, max_files, max_file_bytes, max_total_bytes)
    destination.mkdir()
    for directory in result.directories:
        (destination / directory).mkdir(parents=True, exist_ok=True)
    for path, content in contents.items():
        (destination / path).write_bytes(content)
    return result
