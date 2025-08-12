import subprocess
import time
from conftest import resource_port_tracker
from valkey_test_case import ValkeyTestCase


class TestExternalServer(ValkeyTestCase):
    """
    Test for connecting to a external Valkey server
    """

    def setup_docker_server(self):
        container_name = "valkey-test-external"
        image_name = "valkey/valkey-bundle:latest"

        pull_result = subprocess.run(
            ["docker", "pull", image_name], capture_output=True, text=True
        )
        if pull_result.returncode != 0:
            raise RuntimeError(f"Failed to pull Docker image: {pull_result.stderr}")

        subprocess.run(["docker", "stop", container_name], capture_output=True)
        subprocess.run(["docker", "rm", container_name], capture_output=True)

        cmd = [
            "docker",
            "run",
            "-d",
            "-p",
            "6380:6379",
            "--name",
            container_name,
            image_name,
            "valkey-server",
            "--maxmemory",
            "0",
            "--protected-mode",
            "no",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start Docker container: {result.stderr}")

        time.sleep(2)
        return container_name

    def test_connect_to_external_server(self):
        container_name = None
        try:
            container_name = self.setup_docker_server()

            server, client = self.create_server(
                testdir=self.testdir,
                bind_ip="localhost",
                port=6380,
                external_server=True,
            )

            client.set("hello", "world")
            assert client.get("hello") == b"world"

        except Exception as e:
            print(f"External server test failed: {e}")
            raise

        finally:
            if container_name:
                subprocess.run(["docker", "stop", container_name], capture_output=True)
                subprocess.run(["docker", "rm", container_name], capture_output=True)
