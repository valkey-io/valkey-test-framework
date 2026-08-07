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

**Reusing a Single Server Across All Tests in a Class**

If your tests don't need a fresh server each time (most data-operation tests), use `ReuseServerTestCase` to share one server across the entire class. This avoids the overhead of spawning a new process per test — especially useful when module loading is expensive.

```
class ExampleModuleTestCase(ReuseServerTestCase):
    @pytest.fixture(autouse=True)
    def setup_test(self, setup):
        server_path = "/path_to_your_valkey_server_binary"
        args = {"loadmodule": "/path/to/your/module.so"}
        self.server, self.client = self.create_server(
            testdir=self.testdir, server_path=server_path, args=args
        )

class TestExampleReuse(ExampleModuleTestCase):
    """
    All tests share the same server. Server state is reset between
    tests automatically (FLUSHALL, config restore, ACL reset, etc.)
    for isolation.
    """

    def test_basic1(self):
        self.client.execute_command("SET K V")
        assert self.client.execute_command("GET K") == b"V"

    def test_basic2(self):
        # Previous test's data is flushed — this starts clean
        assert self.client.execute_command("GET K") is None
```

`ReuseServerTestCase` inherits `ValkeyTestCase`, so all existing fixtures, `create_server()` calls, and `self.server`/`self.client` assignments work unchanged. To adopt it in your module, just change the base class — no other code changes needed.

`create_server()` only starts the server on the first call — subsequent calls return the cached instance. Between tests, the overridden `teardown()` resets state instead of killing the server: it issues `RESET` on the shared connection, kills any client connections a test spawned, flushes data/scripts/functions, resets ACL users and the slowlog/latency/ACL logs, and restores any modified config values. If the server becomes unreachable or a config cannot be restored, it is torn down and a fresh one starts for the next test.

If a test creates additional servers (e.g. a server without a module loaded for RDB testing), those are tracked in `server_list` and automatically cleaned up at the end of that test. Only the shared server persists across tests.

Tests run top-to-bottom in definition order (via `pytest-order` with `--order-scope=class`).

For more examples, refer to the `tests` directory of this package.
