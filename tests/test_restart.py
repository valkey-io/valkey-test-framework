from conftest import resource_port_tracker
from valkey_test_case import ValkeyTestCase
import pytest
import sys
import os


class TestRestart(ValkeyTestCase):
    """
    Test the restart machinery and the RDB machinery
    """

    def test_restart(self):
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        additional_startup_args = ""
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=additional_startup_args
        )
        self.client.execute_command("PING")
        self.client.set("a", 1)
        self.client.execute_command("save")
        self.client.set("a", 2)
        self.server.restart(remove_rdb=False)
        self.client = self.server.create_from_server()
        #
        # Prove that the restart didn't overwrite the RDB file.
        #
        assert self.client.get("a") == b'1'
