import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from valkey_test_case import ValkeyTestCase


class TestExternalServer(ValkeyTestCase):
    def test_connect_to_external_server(self):
        """Example: Connect to external Valkey server running on localhost:6379"""
        print("\n=== TESTING EXTERNAL SERVER CONNECTION ===")
        try:
            # Connect to external server instead of creating one
            server, client = self.create_server(
                testdir=self.testdir,
                bind_ip="localhost",
                port=6379,
                external_server=True,
            )

            print("\n RUNNING TEST COMMANDS ON EXTERNAL SERVER")
            # Test basic operations
            client.set("test_key", "test_value")
            assert client.get("test_key") == b"test_value"
            print("External server test completed successfully!")

        except RuntimeError as e:
            # Skip test if external server not available
            import pytest

            pytest.skip(f"External server not available: {e}")
