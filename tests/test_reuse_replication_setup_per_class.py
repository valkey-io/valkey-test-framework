from conftest import resource_port_tracker
from valkey_test_case import ReplicationTestCase
import pytest
import os


class TestExampleReuseReplicationSetupPerClass(ReplicationTestCase):
    """
    Every test will use the same replication setup and the servers will be torn down in the final test.
    This also adds ordering of the tests in a serial manner.
    """

    common_server = None
    common_client = None
    common_replicas = []

    def setup_server_and_client(self):
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        # This is just to avoid a delay on startup for setting up replication.
        additional_startup_args = {
            "repl-diskless-sync": "yes",
            "repl-diskless-sync-delay": "0",
        }
        (
            primary_server,
            TestExampleReuseReplicationSetupPerClass.common_client,
        ) = self.create_server(
            testdir=self.testdir,
            server_path=server_path,
            args=additional_startup_args,
            skip_teardown=True,
        )
        TestExampleReuseReplicationSetupPerClass.common_server = primary_server
        TestExampleReuseReplicationSetupPerClass.common_replicas = (
            self.setup_replication(
                num_replicas=1, skip_teardown=True, primary_server=primary_server
            )
        )

    @pytest.mark.order(1)
    def test_replication_basic1(self):
        # Set up the server and client just one time.
        self.setup_server_and_client()
        server = TestExampleReuseReplicationSetupPerClass.common_server
        replicas = TestExampleReuseReplicationSetupPerClass.common_replicas
        client = TestExampleReuseReplicationSetupPerClass.common_client
        server = TestExampleReuseReplicationSetupPerClass.common_server
        replicas = TestExampleReuseReplicationSetupPerClass.common_replicas
        client.execute_command("SET K V")
        self.waitForReplicaToSyncUp(replicas[0])
        assert replicas[0].client.execute_command("GET K") == b"V"

    @pytest.mark.order(2)
    def test_replication_basic2(self):
        server = TestExampleReuseReplicationSetupPerClass.common_server
        replicas = TestExampleReuseReplicationSetupPerClass.common_replicas
        client = TestExampleReuseReplicationSetupPerClass.common_client
        assert replicas[0].client.execute_command("GET K") == b"V"
        client.execute_command("SET K VV")
        self.waitForReplicaToSyncUp(replicas[0])
        assert replicas[0].client.execute_command("GET K") == b"VV"

    @pytest.mark.order(3)
    def test_replication_basic3(self):
        server = TestExampleReuseReplicationSetupPerClass.common_server
        replicas = TestExampleReuseReplicationSetupPerClass.common_replicas
        replicas[0].client.execute_command("CONFIG SET repl-timeout 5") == b"OK"
        assert replicas[0].client.execute_command("GET K") == b"VV"
        server.exit()
        replicas[0].exit()
