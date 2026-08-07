"""
Demonstrates ReuseServerTestCase usage.

All tests in this class share ONE server. Between each test, the server state
is reset automatically (connection RESET, spawned clients killed, FLUSHALL,
config restore, ACL reset, log resets, etc.) to give each test a clean slate
without the cost of restarting the server.

Tests run top-to-bottom in definition order (via pytest-order with
--order-scope=class). Some tests verify isolation from the previous test,
so ordering matters.
"""

import os
import pytest
from conftest import resource_port_tracker
from valkey_test_case import ReuseServerTestCase


class TestReuseServer(ReuseServerTestCase):
    """Verifies that server reuse works and tests are isolated."""

    @pytest.fixture(autouse=True)
    def setup_test(self, setup):
        version = os.environ.get("SERVER_VERSION", "unstable")
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{version}/valkey-server"
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path
        )

    def test_write_and_read(self):
        """Basic write/read on the shared server."""
        self.client.set("greeting", "hello")
        assert self.client.get("greeting") == b"hello"

    def test_isolation_from_previous(self):
        """Proves FLUSHALL cleaned up the previous test's data."""
        result = self.client.get("greeting")
        assert result is None, "Key from previous test should not exist"

    def test_server_still_alive(self):
        """Proves the server survived across tests (no restart)."""
        assert self.client.ping() is True

    def test_multiple_keys(self):
        """Write multiple keys, verify they all exist within this test."""
        for i in range(10):
            self.client.set(f"key:{i}", f"value:{i}")
        assert self.client.dbsize() == 10

    def test_previous_keys_gone(self):
        """Proves the 10 keys from the previous test were flushed."""
        assert self.client.dbsize() == 0

    def test_config_change_is_restored(self):
        """Proves configs modified during a test get restored for the next."""
        original = self.client.config_get("hz")["hz"]
        self.__class__._original_hz = original
        self.client.config_set("hz", "50")
        assert self.client.config_get("hz")["hz"] == "50"

    def test_config_restored_after_previous(self):
        """Proves the config changed in the previous test was reset."""
        expected = self.__class__._original_hz
        current = self.client.config_get("hz")["hz"]
        assert current == expected, f"Expected hz={expected}, got hz={current}"

    def test_spawn_extra_connection_and_acl_user(self):
        """Leave an extra connection and an ACL user behind for teardown."""
        extra = self.server.get_new_client()
        self.__class__._extra_client_id = extra.execute_command("CLIENT", "ID")
        self.client.execute_command(
            "ACL", "SETUSER", "leaked", "on", ">pw", "~*", "+@all"
        )
        assert self._acl_user_exists("leaked")

    def test_extra_connection_and_acl_user_gone(self):
        """Proves teardown killed the spare connection and deleted the ACL user."""
        # The connection spawned in the previous test should no longer exist.
        live_ids = {
            int(line.split("id=")[1].split(" ")[0])
            for line in self._client_list().splitlines()
            if "id=" in line
        }
        assert (
            self.__class__._extra_client_id not in live_ids
        ), "Spawned connection should have been killed by CLIENT KILL"
        # The ACL user created in the previous test should be gone.
        assert not self._acl_user_exists(
            "leaked"
        ), "ACL user from previous test should have been deleted"

    def _client_list(self):
        result = self.client.execute_command("CLIENT", "LIST")
        return result.decode() if isinstance(result, bytes) else result

    def _acl_user_exists(self, name):
        for entry in self.client.execute_command("ACL", "LIST"):
            if isinstance(entry, bytes):
                entry = entry.decode()
            if entry.startswith(f"user {name} "):
                return True
        return False
