"""
Cluster Teardown Fix Tests

Verifies that a cluster node releases all of its port locks back to the
PortTracker immediately on exit(), so cluster tests (which use several nodes
at once) do not leak or exhaust ports.

Uses the ClusterTestCase / ClusterNodeHandle helpers to build real clusters,
then asserts on the PortTracker's lock bookkeeping across teardown.
"""

import os

from conftest import resource_port_tracker
from valkey_test_case import ClusterTestCase

version = os.environ.get("SERVER_VERSION", "unstable")
SERVER_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    ".build",
    "binaries",
    version,
    "valkey-server",
)


class TestClusterTeardownLeaks(ClusterTestCase):
    """Port locks must be reclaimed the moment a cluster node exits."""

    server_path = SERVER_PATH

    def test_ports_released_after_exit(self):
        """exit() releases all port locks back to the PortTracker immediately."""
        initial = len(self.port_tracker.open_and_locked_files)

        self.create_cluster(3)

        # Each node reserves 3 locks (base, cluster bus, search coordinator).
        after_create = len(self.port_tracker.open_and_locked_files)
        assert (
            after_create - initial == 9
        ), "3 nodes x 3 locks each = 9 locks while running"

        for node in self.nodes:
            node.exit()

        after_exit = len(self.port_tracker.open_and_locked_files)
        assert after_exit == initial, (
            "all port locks should be released after exit(), "
            f"{after_exit - initial} still held"
        )

    def test_repeated_cluster_creation_no_exhaustion(self):
        """Creating and destroying clusters repeatedly does not exhaust ports."""
        initial = len(self.port_tracker.open_and_locked_files)

        for _ in range(5):
            self.create_cluster(3)
            for node in self.nodes:
                node.exit()
            # Reset our node list so the next round starts clean.
            self.nodes = []
            assert (
                len(self.port_tracker.open_and_locked_files) == initial
            ), "ports must be reclaimed after each cluster teardown"

    def test_double_exit_safe(self):
        """Calling exit() twice on a node does not crash or double-release."""
        initial = len(self.port_tracker.open_and_locked_files)

        node = self.create_node()
        node.start(connect_client=True)

        node.exit()
        node.exit()

        assert (
            len(self.port_tracker.open_and_locked_files) == initial
        ), "double exit() must leave no locks held and not error"

    def test_restart_keeps_port_reserved(self):
        """restart() calls exit() but must NOT release the port locks — the
        node has to come back up on the same port."""
        initial = len(self.port_tracker.open_and_locked_files)

        node = self.create_node()
        node.start(connect_client=True)
        port = node.port
        after_start = len(self.port_tracker.open_and_locked_files)
        assert after_start - initial == 3, "one node reserves 3 port locks"

        node.restart()

        # The port locks are still held and the node is back on the same port.
        assert (
            len(self.port_tracker.open_and_locked_files) == after_start
        ), "restart() must keep the node's port locks reserved"
        assert node.port == port
        assert node.client.ping() is True

        # A normal exit afterward releases them.
        node.exit()
        assert (
            len(self.port_tracker.open_and_locked_files) == initial
        ), "exit() after restart still releases the port locks"
