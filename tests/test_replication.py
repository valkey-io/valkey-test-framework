from conftest import resource_port_tracker
from valkey_test_case import ReplicationTestCase
import pytest
import sys
import os


class TestExampleReplication(ReplicationTestCase):
    @pytest.fixture(autouse=True)
    def setup_test(self, setup):
        # This is just to avoid a delay on startup for setting up replication.
        additional_startup_args = {
            "repl-diskless-sync": "yes",
            "repl-diskless-sync-delay": "0",
        }
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=additional_startup_args
        )

    def test_replication(self):
        self.setup_replication(num_replicas=1)
        self.client.execute_command("SET K V")
        self.waitForReplicaToSyncUp(self.replicas[0])
        assert self.replicas[0].client.execute_command("GET K") == b"V"
