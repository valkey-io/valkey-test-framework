import pytest

# Add the src directory to sys.path
# TODO: Once we publish this package to PyPI, update the paths for importing these test resources.
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))
from valkey_test_case import ValkeyTestCase
from conftest import resource_port_tracker

class TestCaseBase(ValkeyTestCase):
    @pytest.fixture(autouse=True)
    def setup_test(self, setup):
        server_path = f"{os.path.dirname(os.path.realpath(__file__))}/.build/binaries/{os.environ['SERVER_VERSION']}/valkey-server"
        additional_startup_args = ""
        self.server, self.client = self.create_server(testdir = self.testdir,  server_path=server_path, args=additional_startup_args)

class TestBasic(TestCaseBase):

    def test_basic(self):
        client = self.server.get_new_client()
        client.execute_command('PING')
