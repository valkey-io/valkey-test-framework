from conftest import resource_port_tracker
from valkey_test_case import ValkeyTestCase
import pytest
import sys
import os


class TestExamplePerTestSetup(ValkeyTestCase):
    """
    Every test in this class will have a custom setup that is defined individually.
    """

    def test_per_test_setup(self):
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        additional_startup_args = ""
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=additional_startup_args
        )
        self.client.execute_command("PING")

    def test_per_test_setup_memory_limit_arg_example(self):
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        additional_startup_args = {"maxmemory": "1kb"}
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=additional_startup_args
        )
        self.client.execute_command("PING")
        try:
            self.client.execute_command("SET KEY VAL")
            assert (
                False
            ), f"SET command executed correctly when it should have failed due to memory > 'maxmemory"
        except Exception as e:
            assert str(e) == "command not allowed when used memory > 'maxmemory'."

        self.new_server, self.new_client = self.create_server(
            testdir=self.testdir,
            server_path=server_path,
        )
        self.new_client.execute_command("SET KEY VAL")
