from conftest import resource_port_tracker
from valkey_test_case import ValkeyTestCase
import pytest
import sys
import os


class TestExampleReuseSetupPerClass(ValkeyTestCase):
    """
    Every test will use the same server and client instance and the server will be torn down in the final test.
    This also adds ordering of the tests in a serial manner.
    """

    common_server = None
    common_client = None

    def setup_server_and_client(self):
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        additional_startup_args = ""
        (
            TestExampleReuseSetupPerClass.common_server,
            TestExampleReuseSetupPerClass.common_client,
        ) = self.create_server(
            testdir=self.testdir,
            server_path=server_path,
            args=additional_startup_args,
            skip_teardown=True,
        )

    @pytest.mark.order(1)
    def test_basic1(self):
        # Set up the server and client just one time.
        self.setup_server_and_client()
        TestExampleReuseSetupPerClass.common_client.execute_command("PING")

    @pytest.mark.order(2)
    def test_basic2(self):
        TestExampleReuseSetupPerClass.common_client.execute_command("PING")
        c = TestExampleReuseSetupPerClass.common_server.get_new_client()
        c.execute_command("PING")

    @pytest.mark.order(3)
    def test_basic3(self):
        TestExampleReuseSetupPerClass.common_client.execute_command("SET K V")
        TestExampleReuseSetupPerClass.common_server.exit()
