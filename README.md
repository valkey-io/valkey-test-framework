# valkey-test-framework
Valkey-test-frmaework is a python framework for creating integration testwork for Valkey. With this users can easily set up python integration tests for modules ...(Others?). This framwork allows for replication testing using the `ReplicationTestCase` and for default builds in Valkey. This package allows the user to specify specific versions of Valkey that you may want to test against as well as letting you change startup arguments as you need.

## Build instructions

```
git clone https://github.com/valkey-io/valkey-test-framework.git
cd valkey-test-framework
./build.sh
```

## Specifying on a test level

If you want to have specific start up for certain tests, first inherit ValkeyTestCase then in your test class put the following at the beginning:
```
    args = {"argument_name":"argument_value", "argument_name":"argument_value"}
    server_path = "path_to_your_valkey_server_binary"
    self.server, self.client = self.create_server(testdir = self.testdir,  server_path=server_path, args=args)
```

## Specifying on a package level

If you want all tests to have the same startup arguments then we have made this simple by reducing the number of times that you need to specify arguments or version. In your test directory add a python file with name of your choosing and have every test inherit the class where you specify the code below:

```
class UsersTestCaseBase(ValkeyTestCase):

    @pytest.fixture(autouse=True)
    def setup_test(self, setup):
        args = {"argument_name":"argument_value", "argument_name":"argument_value"}
        server_path = "path_to_your_valkey_server_binary"
        self.server, self.client = self.create_server(testdir = self.testdir,  server_path=server_path, args=args)
```

This framework is designed to be flexible so you can mix and match arguments and server version