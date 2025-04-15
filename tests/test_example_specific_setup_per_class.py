from conftest import resource_port_tracker
from valkey_test_case import ValkeyTestCase
import pytest
import sys
import os


class ExampleTestCaseBase(ValkeyTestCase):
    @pytest.fixture(autouse=True)
    def setup_test(self, setup):
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        additional_startup_args = ""
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=additional_startup_args
        )


class TestExamplePerClassSetup(ExampleTestCaseBase):
    """
    Every test will use the same server startup from the ExampleTestCaseBase.
    """

    def test_basic1(self):
        client = self.server.get_new_client()
        client.execute_command("PING")

    def test_basic2(self):
        client = self.server.get_new_client()
        client.execute_command("SET K V")
