# valkey-test-framework
Valkey-test-framework is a python framework for creating integration tests using Valkey. With this, users developing software around Valkey (e.g Modules, extensions to Valkey, or even core Valkey itself) can easily set up python integration tests to validate functionality. The framework is designed to be simple and flexible.

It allows various functionalities including: Starting up custom Valkey Servers per TestClass or per individual Test, Customizing server startup arguments (e.g. module load, configs), custom server binary path, Replication Testing, Waiter functionality, etc.

It uses pytest for identifying test files (and running the individual test classes containing all the tests). The framework is compatible with pytest verions up till 7.4.3.

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

For more examples, refer to the `tests` directory of this package.
