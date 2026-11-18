"""Verify a loopback listener belongs to the exact child server on Linux.

This closes the ordinary free-port/bind race; it is not protection against a
malicious same-UID host process or a compromised kernel. No candidate has proc
or network access to these host identities.
"""

import os
from pathlib import Path


class EndpointOwnershipError(RuntimeError):
    pass


def process_identity(pid, proc_root=Path("/proc")):
    fields = (proc_root / str(pid) / "stat").read_text().rsplit(") ", 1)[1].split()
    if fields[0] in {"Z", "X"}:
        raise EndpointOwnershipError("Server process is no longer live")
    return {
        "pid": pid,
        "start_ticks": fields[19],
        "network_namespace": os.readlink(proc_root / str(pid) / "ns/net"),
    }


def owned_listener(identity, port, proc_root=Path("/proc")):
    """False while not bound; refuse any foreign listener at the selected port."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    pid = identity["pid"]
    try:
        if process_identity(pid, proc_root) != identity:
            raise EndpointOwnershipError("Server process identity changed")
        table = proc_root / str(pid) / "net/tcp"
        with table.open() as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise EndpointOwnershipError("Listener table exceeds inspection bound")
        listeners = set()
        for line in data.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            address, hex_port = fields[1].split(":")
            if int(hex_port, 16) == port and address in {"0100007F", "00000000"}:
                listeners.add(fields[9])
        if not listeners:
            return False
        sockets = set()
        for fd in (proc_root / str(pid) / "fd").iterdir():
            try:
                target = os.readlink(fd)
            except FileNotFoundError:
                continue
            if target.startswith("socket:[") and target.endswith("]"):
                sockets.add(target[8:-1])
        if not listeners <= sockets:
            raise EndpointOwnershipError(
                "Selected endpoint is owned by another process"
            )
        if process_identity(pid, proc_root) != identity:
            raise EndpointOwnershipError("Server identity changed during inspection")
        return {
            "identity": identity,
            "port": port,
            "listener_inodes": sorted(listeners),
        }
    except (OSError, ValueError, IndexError) as error:
        raise EndpointOwnershipError(
            f"Cannot establish owned listener: {error}"
        ) from error
