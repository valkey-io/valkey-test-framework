"""
Slot Migration Tests

Verifies ClusterTestCase.migrate_slot(): a slot (and the keys in it) moves from
one node to another on a live cluster, ownership updates across the cluster, and
the keys are served from the new owner afterward. Covers key movement (incl.
slots larger than one batch), multi-DB (requires cluster-databases > 1),
caller-DB isolation, cluster-wide ownership, empty-slot, and replica-shard
migrations.
"""

import os

from conftest import resource_port_tracker
from valkey_test_case import ClusterTestCase
from util.waiters import wait_for_equal
from valkey.cluster import key_slot

version = os.environ.get("SERVER_VERSION", "unstable")
SERVER_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    ".build",
    "binaries",
    version,
    "valkey-server",
)


class TestSlotMigration(ClusterTestCase):
    """Move slots between live nodes and confirm data follows."""

    server_path = SERVER_PATH

    def _pick_source_and_target(self, slot):
        source = self.get_slot_owner(slot)
        target = next(n for n in self.nodes if n.nodeid != source.nodeid)
        return source, target

    def test_migrate_slot_moves_keys(self):
        """All keys in a slot move to the new owner, and their values survive."""
        self.setup_cluster(num_shards=2, num_replicas_per_shard=0)

        # Hash tag {m} forces every key into the same slot. Use enough keys to
        # cross the 100-key GETKEYSINSLOT batch boundary migrate_slot drains.
        slot = key_slot(b"{m}")
        source, target = self._pick_source_and_target(slot)
        for i in range(250):
            source.client.set(f"{{m}}:{i}", i)
        assert source.count_keys_in_slot(slot) == 250

        self.migrate_slot(source, target, slot)
        self.wait_for_slot_owner(slot, target)

        assert source.count_keys_in_slot(slot) == 0
        assert target.count_keys_in_slot(slot) == 250
        # A specific key's value survived the move, not just the count.
        assert target.client.get("{m}:0") == b"0"

    def test_migrate_slot_multiple_databases(self):
        """Keys sharing a slot across several DBs all move (cluster-databases)."""
        self.args["cluster-databases"] = "16"
        self.setup_cluster(num_shards=2, num_replicas_per_shard=0)

        key = "mdkey"
        slot = key_slot(key.encode())
        source, target = self._pick_source_and_target(slot)

        dbs = (0, 1, 2)
        for db in dbs:
            source.create_from_server(db=db).set(key, f"v{db}")

        self.migrate_slot(source, target, slot, dbs=dbs)
        self.wait_for_slot_owner(slot, target)

        for db in dbs:
            assert target.create_from_server(db=db).get(key) == f"v{db}".encode()

    def test_migrate_does_not_disturb_caller_db(self):
        """migrate_slot must not change the DB the caller's client is on."""
        self.args["cluster-databases"] = "16"
        self.setup_cluster(num_shards=2, num_replicas_per_shard=0)

        key = "dbkey"
        slot = key_slot(key.encode())
        source, target = self._pick_source_and_target(slot)

        # Put the source client on DB 3 before migrating.
        source.client.execute_command("SELECT", 3)
        source.client.set(key, "x")

        self.migrate_slot(source, target, slot, dbs=(3,))
        self.wait_for_slot_owner(slot, target)

        # The source client must still be on DB 3 (migrate used its own conn).
        info = source.client.execute_command("CLIENT", "INFO")
        info = info.decode() if isinstance(info, bytes) else info
        assert " db=3 " in info, f"caller client left on wrong DB: {info}"
        # And the key really did move to DB 3 on the target.
        assert target.create_from_server(db=3).get(key) == b"x"

    def test_ownership_updates_across_cluster(self):
        """Every node agrees the target owns the slot after migration."""
        self.setup_cluster(num_shards=2, num_replicas_per_shard=0)

        slot = key_slot(b"ownerkey")
        source, target = self._pick_source_and_target(slot)

        self.migrate_slot(source, target, slot)
        self.wait_for_slot_owner(slot, target)

        for node in self.nodes:
            assert node.get_slot_owner_id(slot) == target.nodeid

    def test_migrate_empty_slot(self):
        """Migrating a slot with no keys still transfers ownership cleanly."""
        self.setup_cluster(num_shards=2, num_replicas_per_shard=0)

        slot = key_slot(b"emptykey")
        source, target = self._pick_source_and_target(slot)
        assert source.count_keys_in_slot(slot) == 0

        self.migrate_slot(source, target, slot)
        self.wait_for_slot_owner(slot, target)

        assert self.get_slot_owner(slot).nodeid == target.nodeid

    def test_migrate_with_replicas(self):
        """Migration works when shards have replicas.

        CLUSTER SETSLOT is only valid on primaries, so migrate_slot must skip
        replica nodes; the migrated key must also reach the target's replica.
        """
        self.setup_cluster(num_shards=2, num_replicas_per_shard=1)

        key = "replkey"
        slot = key_slot(key.encode())
        source = self.get_slot_owner(slot)
        # target = the other primary (a node that owns some slots, not source)
        target = next(
            n for n in self.nodes if n.is_primary() and n.nodeid != source.nodeid
        )
        source.client.set(key, "payload")

        self.migrate_slot(source, target, slot)
        self.wait_for_slot_owner(slot, target)

        assert target.client.get(key) == b"payload"

        # The key should replicate to the target primary's replica.
        replica = next(n for n in self.nodes if n.masterid == target.nodeid)
        replica.client.execute_command("READONLY")
        wait_for_equal(lambda: replica.client.get(key), b"payload")
