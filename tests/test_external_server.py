from conftest import resource_port_tracker
from valkey_test_case import ValkeyTestCase


class TestExternalServer(ValkeyTestCase):
    def test_connect_to_external_server(self):
        """Example: Connect to external Valkey server running on localhost:6379"""
        try:
            # Connect to external server instead of creating one
            server, client = self.create_server(
                testdir=self.testdir,
                bind_ip="localhost",
                port=6379,
                external_server=True,
            )

            # Test basic operations
            client.set("hello", "world")
            assert client.get("hello") == b"world"

        except RuntimeError as e:
            # Skip test if external server not available
            import pytest
            pytest.skip(f"External server not available: {e}")
