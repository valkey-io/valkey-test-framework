"""
Minimal conftest.py for external server tests
"""

import pytest
import fcntl
import socket
import os
import tempfile
from pathlib import Path


class PortTracker(object):
    CLUSTER_BUS_PORT_OFFSET = 10000
    MIN_PORT = 5000
    MAX_PORT = 32768
    MAX_BASE_PORT = MAX_PORT - CLUSTER_BUS_PORT_OFFSET - MIN_PORT
    MAX_RETRIES = 100
    LOCKS_DIR = os.path.join(tempfile.gettempdir(), "port_tracker")

    def __init__(self, node_id):
        self._hash = hash(str(node_id))
        if not os.path.exists(Path(PortTracker.LOCKS_DIR)):
            Path(PortTracker.LOCKS_DIR).mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        self.open_and_locked_files = {}
        return self

    def __exit__(self, type, value, tb):
        for lockfile in self.open_and_locked_files.values():
            self._try_remove(lockfile)

    def _try_remove(self, lockfile):
        lockfile.close()
        try:
            os.remove(lockfile.name)
        except:
            pass

    def _next_port(self):
        self._hash = hash(str(self._hash))
        return (self._hash % PortTracker.MAX_BASE_PORT) + PortTracker.MIN_PORT

    def _try_lock_port(self, port):
        lockfilename = os.path.join(self.LOCKS_DIR, "port%d.lock" % port)
        lockfile = open(lockfilename, "w")
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._try_remove(lockfile)
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                lockfile.close()
                return False
        self.open_and_locked_files[port] = lockfile
        return True

    def _unlock_port(self, port):
        lockfile = self.open_and_locked_files.get(port)
        if lockfile:
            lockfile.close()
            del self.open_and_locked_files[port]

    def get_unused_port(self):
        for r in range(PortTracker.MAX_RETRIES):
            port = self._next_port()
            if not self._try_lock_port(port):
                continue
            if not self._try_lock_port(port + PortTracker.CLUSTER_BUS_PORT_OFFSET):
                self._unlock_port(port)
                continue
            return port
        assert False, "Failed to find port after %d tries" % PortTracker.MAX_RETRIES


@pytest.fixture(scope="function", autouse=True)
def resource_port_tracker(request):
    """Create port tracker for each pytest worker"""
    with PortTracker(request.node.nodeid) as p:
        yield p
