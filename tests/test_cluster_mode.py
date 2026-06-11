from conftest import resource_port_tracker
from valkey_test_case import ClusterTestCase, ClusterInfo
import pytest
import os


SERVER_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    ".build",
    "binaries",
    os.environ["SERVER_VERSION"],
    "valkey-server",
)


class TestClusterBasic(ClusterTestCase):
    """Verify that ClusterTestCase can bootstrap a 3-primary cluster."""

    server_path = SERVER_PATH

    @pytest.mark.order(1)
    def test_setup_cluster_and_use(self):
        client = self.setup_cluster(num_shards=3, num_replicas_per_shard=0)

        # Verify cluster_state is ok on all nodes
        for node in self.nodes:
            assert ClusterInfo(
                node.client.cluster("INFO")
            ).is_cluster_ok(), f"Node {node.port} not in ok state"

        # Verify all 16384 slots are assigned
        info = ClusterInfo(self.nodes[0].client.cluster("INFO"))
        assert info.cluster_slots_assigned() == 16384
        assert info.cluster_known_nodes() == 3

        # Write and read keys — ValkeyCluster follows MOVED redirections
        for i in range(100):
            client.set(f"key:{i}", f"value:{i}")

        for i in range(100):
            val = client.get(f"key:{i}")
            assert val == b"value:" + str(i).encode()

    @pytest.mark.order(2)
    @pytest.mark.parametrize("num_shards", [2, 3, 5])
    def test_slot_distribution(self, num_shards):
        self.setup_cluster(num_shards=num_shards, num_replicas_per_shard=0)

        # Collect the set of slots each primary owns from CLUSTER SLOTS.
        # Reply shape: [[start, end, [host, port, node_id, ...], ...], ...]
        owned = {}
        for slot_range in self.nodes[0].client.cluster("SLOTS"):
            start, end = slot_range[0], slot_range[1]
            owner_id = slot_range[2][2].decode()
            owned.setdefault(owner_id, set()).update(range(start, end + 1))

        # Every primary owns a share of the slots.
        assert len(owned) == num_shards

        all_slots = set()
        for slots in owned.values():
            # No slot is claimed by more than one primary.
            assert all_slots.isdisjoint(slots)
            all_slots |= slots

        # Every one of the 16384 slots is covered exactly once.
        assert all_slots == set(range(16384))


class TestClusterWithReplicas(ClusterTestCase):
    """Verify multi-shard clusters with replicas."""

    server_path = SERVER_PATH

    @pytest.mark.order(1)
    def test_setup_cluster_with_replicas(self):
        client = self.setup_cluster(num_shards=3, num_replicas_per_shard=1)

        # 6 nodes total
        assert len(self.nodes) == 6

        # Cluster is healthy
        for node in self.nodes:
            assert ClusterInfo(
                node.client.cluster("INFO")
            ).is_cluster_ok(), f"Node {node.port} not in ok state"

        # All slots assigned
        info = ClusterInfo(self.nodes[0].client.cluster("INFO"))
        assert info.cluster_slots_assigned() == 16384
        assert info.cluster_known_nodes() == 6

        # Replicas have master IDs set
        for i in range(3, 6):
            assert self.nodes[i].masterid is not None

        # Write/read through cluster client
        for i in range(50):
            client.set(f"rkey:{i}", f"rval:{i}")
        for i in range(50):
            assert client.get(f"rkey:{i}") == f"rval:{i}".encode()

    @pytest.mark.order(2)
    def test_setup_cluster_multiple_replicas_per_shard(self):
        # 2 shards x (1 primary + 2 replicas) = 6 nodes
        self.setup_cluster(num_shards=2, num_replicas_per_shard=2)

        assert len(self.nodes) == 6

        # Cluster is healthy and every node sees all 6
        for node in self.nodes:
            info = ClusterInfo(node.client.cluster("INFO"))
            assert info.is_cluster_ok(), f"Node {node.port} not in ok state"
            assert info.cluster_known_nodes() == 6

        # Each primary has exactly 2 replicas online.
        for i in range(2):
            assert self.nodes[i].num_replicas_online() == 2

        # Every replica is attached to one of the two primaries.
        primary_ids = {self.nodes[0].nodeid, self.nodes[1].nodeid}
        for i in range(2, 6):
            assert self.nodes[i].masterid in primary_ids
