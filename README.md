# valkey-test-framework
Valkey-test-framework is a python framework for creating integration tests using Valkey. With this, users developing software around Valkey (e.g Modules, extensions to Valkey, or even core Valkey itself) can easily set up python integration tests to validate functionality. The framework is designed to be simple and flexible.

It allows various functionalities including: Starting up custom Valkey Servers per TestClass or per individual Test, Customizing server startup arguments (e.g. module load, configs), custom server binary path, Replication Testing, Waiter functionality, etc.

It uses pytest for identifying test files (and running the individual test classes containing all the tests). The framework is compatible with pytest versions up till 7.4.3.

## Build instructions

```
git clone https://github.com/valkey-io/valkey-test-framework.git
cd valkey-test-framework
./build.sh
```

## Usage

**Using a customized Valkey Server per Individual Test**

If you want to have a specific start up for certain tests, first inherit ValkeyTestCase in your test class, and then customize the server creation per individual test. 
```
class TestExamplePerTestSetup(ValkeyTestCase):
    def test_basic1(self):
        server_path = "/path_to_your_valkey_server_binary"
        additional_startup_args = {"config1_name":"config_value1", "config2_name":"config_value2"}
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=additional_startup_args
        )
        self.client.execute_command("PING")

    def test_basic2(self):
        server_path = "/path_to_your_valkey_server_binary"
        # Example of no startup args
        additional_startup_args = ""
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=additional_startup_args
        )
        self.client.execute_command("SET K V")
```

**Using a customized Valkey Server per Test Class**

If you want all tests to have the same startup arguments, we have made this simple by reducing the number of times that you need to specify arguments or version. Have a Base Class that does a common server setup and have every Test Class inherit the common Base Class:

```
class ExampleTestCaseBase(ValkeyTestCase):
    @pytest.fixture(autouse=True)
    def setup_test(self, setup):
        server_path = "/path_to_your_valkey_server_binary"
        # Example of no startup args
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
```

**Testing Cluster Mode Enabled (CME)**

To test against a Valkey cluster, inherit `ClusterTestCase` instead of `ValkeyTestCase`. Call `setup_cluster(num_shards, num_replicas_per_shard)` to bootstrap a cluster: it starts all nodes, assigns slots, attaches replicas, waits until the cluster state is `ok`, and returns a client that follows `MOVED`/`ASK` redirections. The cluster is torn down automatically after each test.

```
from valkey_test_case import ClusterTestCase, ClusterInfo

class TestExampleCluster(ClusterTestCase):
    def test_cluster_read_write(self):
        self.server_path = "/path_to_your_valkey_server_binary"

        # 3 primaries, each with 1 replica (6 nodes total)
        client = self.setup_cluster(num_shards=3, num_replicas_per_shard=1)

        client.set("key", "value")
        assert client.get("key") == b"value"

        # self.nodes holds every ClusterNodeHandle for direct inspection
        for node in self.nodes:
            assert ClusterInfo(node.client.cluster("INFO")).is_cluster_ok()
```

To apply startup arguments (modules, configs) to every node, set `self.args` inside the test before calling `setup_cluster`.

To test slot migration, use `migrate_slot(source, target, slot)` to move a slot and its keys from one node to another, then `wait_for_slot_owner(slot, target)` to wait until every node agrees on the new owner. `get_slot_owner(slot)` returns the node that currently owns a slot.

```
from valkey_test_case import ClusterTestCase
from valkey.cluster import key_slot

class TestExampleMigration(ClusterTestCase):
    def test_migrate(self):
        self.server_path = "/path_to_your_valkey_server_binary"
        self.setup_cluster(num_shards=2, num_replicas_per_shard=0)

        slot = key_slot(b"key")
        source = self.get_slot_owner(slot)
        target = next(n for n in self.nodes if n.nodeid != source.nodeid)
        source.client.set("key", "value")

        self.migrate_slot(source, target, slot)
        self.wait_for_slot_owner(slot, target)
        assert target.client.get("key") == b"value"
```

Pass `dbs=(0, 1, ...)` to `migrate_slot` to move keys across multiple databases; migrating any database other than 0 requires the cluster to be started with `cluster-databases > 1`.
