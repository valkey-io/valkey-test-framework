import subprocess
import time
import os
import pytest
import shutil
import re
from contextlib import contextmanager
from functools import wraps
from valkey import *
from util.waiters import *

from enum import Enum

MAX_PING_TRIES = 60

# The maximum wait time for operations in the tests
TEST_MAX_WAIT_TIME_SECONDS = 90
MAX_REPLICA_WAIT_TIME = 120
MAX_SYNC_WAIT = 90
MAX_PING_WAIT_TIME = 30


# Return true if the specified string is present in the provided file
def verify_string_in_file(string, filename):
    if not os.path.exists(filename):
        return False

    with open(filename) as f:
        for line in f:
            if string in line:
                return True
    return False


# Return true if the any of the strings is present in the provided file
def verify_any_of_strings_in_file(strings, filename):
    if not os.path.exists(filename):
        return False

    with open(filename, encoding="latin-1") as f:
        for line in f:
            for string in strings:
                if string in line:
                    return True
    return False


class ExpectException(Exception):
    def __init__(self, lhs, op, rhs):
        self.lhs = lhs
        self.op = op
        self.rhs = rhs


def expect(lhs, op, rhs):
    if not op(lhs, rhs):
        raise ExpectException(lhs, op, rhs)


class ValkeyAction(Enum):
    AOF_REWRITE = 1


class ValkeyServerHandle(object):
    """Handle to a valkey server process"""

    DEFAULT_BIND_IP = "0.0.0.0"

    def __init__(
        self,
        bind_ip,
        port,
        port_tracker,
        server_path="valkey-server",
        cwd=".",
        external_mode=False,
    ):
        self.server = None
        self.client = None
        self.external_mode = external_mode
        self.port = port
        self.bind_ip = bind_ip
        self.args = {}
        self.args["port"] = self.port
        self.args["logfile"] = f"logfile_{port}"
        self.args["dbfilename"] = f"testrdb-{port}.rdb"
        self.args["appenddirname"] = f"aof-{port}"
        self.cwd = cwd
        self.valkey_path = server_path
        self.conf_file = None

    def create_from_server(self, db=0):
        logging.info(("Created regular client for port {}".format(self.port)))
        r = StrictValkey(host=self.bind_ip, port=self.port, db=db)
        return r

    def set_startup_args(self, args):
        self.args.update(args)

    def get_new_client(self):
        return self.create_from_server()

    def exit(self, cleanup=True, remove_nodes_conf=True):
        if self.client:
            if not self.external_mode:
                try:
                    self.client.execute_command("shutdown nosave")
                except:
                    logging.warning("SHUTDOWN was unsuccessful")
            self.client.close()
            self.client = None

        # No server process to clean up if we're using an external server
        if self.external_mode:
            return

        if self.server:
            self._waitForExit()
            self.server = None

        if os.environ.get("SKIPLOGCLEAN") == None:
            if "logfile" in self.args and os.path.exists(
                os.path.join(self.cwd, self.args["logfile"])
            ):
                os.remove(os.path.join(self.cwd, self.args["logfile"]))

            if (
                cleanup
                and "appenddirname" in self.args
                and os.path.exists(os.path.join(self.cwd, self.args["appenddirname"]))
            ):
                shutil.rmtree(os.path.join(self.cwd, self.args["appenddirname"]))

        if (
            cleanup
            and "dbfilename" in self.args
            and os.path.exists(os.path.join(self.cwd, self.args["dbfilename"]))
        ):
            try:
                os.remove(os.path.join(self.cwd, self.args["dbfilename"]))
            except OSError:
                os.rmdir(os.path.join(self.cwd, self.args["dbfilename"]))

        if (
            remove_nodes_conf
            and "cluster-config-file" in self.args
            and os.path.exists(os.path.join(self.cwd, self.args["cluster-config-file"]))
        ):
            try:
                os.remove(os.path.join(self.cwd, self.args["cluster-config-file"]))
            except OSError:
                os.rmdir(os.path.join(self.cwd, self.args["cluster-config-file"]))

    def _waitForExit(self):
        try:
            self.wait_for_shutdown()
        except WaitTimeout:
            logging.warning("Server did not exit in time, killing...")
            if self.is_alive():
                # check server is still running before kill it.
                self.server.kill()
            try:
                self.wait_for_shutdown()
            except WaitTimeout:
                logging.error("Could not tear down server")
                assert False

    def pid(self):
        return self.server.pid

    def wait_for_shutdown(self):
        wait_for_ne(
            lambda: self.server.poll(), None, timeout=TEST_MAX_WAIT_TIME_SECONDS
        )

    def children_pids(self):
        process = subprocess.Popen(
            "ps --no-headers -o pid --ppid %s" % self.pid(),
            shell=True,
            stdout=subprocess.PIPE,
        )
        children = list()
        for line in process.communicate()[0].split("\n"):
            line = line.strip()
            if line != "":
                children.append(line)
        return children

    def wait_for_replicas(self, num_of_replicas):
        wait_for_equal(
            lambda: self.client.info(section="replication")["connected_slaves"],
            num_of_replicas,
            timeout=MAX_REPLICA_WAIT_TIME,
        )

    def wait_for_ready_to_accept_connections(self):
        logfile = os.path.join(self.cwd, self.args["logfile"])
        strings = ["Ready to accept connections"]
        wait_for_true(
            lambda: verify_any_of_strings_in_file(strings, logfile),
            timeout=TEST_MAX_WAIT_TIME_SECONDS,
        )

    def verify_string_in_logfile(self, string):
        logfile = os.path.join(self.cwd, self.args["logfile"])
        return verify_string_in_file(string, logfile)

    @contextmanager
    def expect_crash(self, valkey_test, timeout=30, period=0.1):
        valkey_test.crash_expected = True
        try:
            yield
        except Exception:
            pass
        finally:
            start_time = time.time()
            while self.is_alive() and time.time() < start_time + timeout:
                time.sleep(period)
            if self.is_alive():
                pytest.fail(
                    f"Valkey server did not crash as expected within {time.time() - start_time} seconds. "
                )

    def start(self, wait_for_ping=True, connect_client=True):
        if self.server:
            raise RuntimeError("Server already started")
        server_args = []
        if "VALGRIND_OPTIONS" in os.environ:
            server_args.extend(["valgrind", os.environ["VALGRIND_OPTIONS"]])
        server_args.extend([self.valkey_path])

        # If configuration file was provided, pass it
        if self.conf_file:
            server_args.append(self.conf_file)

        # Append the remaining arguments
        for k, v in list(self.args.items()):
            server_args.append("--" + k.replace("_", "-"))
            args = str(v).split()
            for arg in args:
                server_args.append(arg)

        logging.info(server_args)

        # Provide some warnings to help debug failing tests
        if "cluster-config-file" in self.args and os.path.exists(
            os.path.join(self.cwd, self.args["cluster-config-file"])
        ):
            logging.info(
                (
                    "cluster-config-file exists ({}) before startup for node with port {}".format(
                        os.path.join(os.getcwd(), self.args["cluster-config-file"]),
                        self.port,
                    )
                )
            )

        if "dbfilename" in self.args and os.path.exists(
            os.path.join(self.cwd, self.args["dbfilename"])
        ):
            logging.info(
                "dbfilename exists before startup for node with port %d" % self.port
            )

        self.server = subprocess.Popen(server_args, cwd=self.cwd)
        if connect_client:
            try:
                self.wait_for_ready_to_accept_connections()
            except WaitTimeout:
                raise RuntimeError("Valkey server is not Ready to accept connections")
            if wait_for_ping:
                try:
                    self.connect()
                except:
                    # It's possible that the port was not fully released, so try again
                    self.server.kill()
                    time.sleep(1)
                    self.server = subprocess.Popen(server_args, cwd=self.cwd)
                    self.connect()

        return self.client

    def restart(self, remove_rdb=True, remove_nodes_conf=True, connect_client=True):
        if self.external_mode:
            return self._test_instance.restart_external_server(
                self, remove_rdb, remove_nodes_conf, connect_client
            )
        else:
            self.exit(remove_rdb, remove_nodes_conf)
            self.start(connect_client=connect_client)

    def is_alive(self):
        return self._is_alive(self.client)

    def _is_alive(self, c):
        try:
            c.ping()
            return True
        except:
            return False

    def connection_is_alive(self, c):
        try:
            c.ping()
            return True
        except:
            return False

    def _waitForPing(self, c):
        try:
            wait_for_true(lambda: self._is_alive(c), timeout=MAX_PING_WAIT_TIME)
            return True
        except (ConnectionError, TimeoutError) as e:
            logging.error(e)
            return False

    def wait_for_key(self, key, value):
        if isinstance(value, str):
            value = value.encode()
        wait_for_equal(
            lambda: self.client.get(key), value, timeout=TEST_MAX_WAIT_TIME_SECONDS
        )

    def connect(self):
        self.client = self.create_from_server()

        def safeping(client):
            try:
                client.ping()
                return True
            except:
                return False

        wait_for_true(lambda: safeping(self.client), timeout=TEST_MAX_WAIT_TIME_SECONDS)
        return self.client

    def wait_for_save_done(self, client=None):
        """Wait for the save to complete, failing if it does not complete successfully in the timeout"""
        if client is None:
            client = self.client
        try:
            wait_for_ne(
                lambda: client.info()["rdb_bgsave_in_progress"],
                1,
                timeout=TEST_MAX_WAIT_TIME_SECONDS,
            )
        except WaitTimeout:
            raise RuntimeError("Save failed to complete in time")
        assert client.info()["rdb_last_bgsave_status"] == "ok"

    def wait_for_save_in_progress(self, client=None):
        if client is None:
            client = self.client
        wait_for_equal(
            lambda: client.info()["rdb_bgsave_in_progress"],
            1,
            timeout=TEST_MAX_WAIT_TIME_SECONDS,
        )

    def is_rdb_done_loading(self):
        if self.external_mode:
            info = self.client.info()
            return info.get("loading", 0) == 0
        else:
            # Local server logic
            rdb_load_log = "Done loading RDB"
            return self.verify_string_in_logfile(rdb_load_log) == True

    def num_replicas_online(self, client=None):
        if client is None:
            client = self.client
        count = 0
        for k, v in client.info(section="replication").items():
            if re.match("^slave[0-9]", k) and v["state"] == "online":
                count += 1
        return count

    def get_default_client(self, client):
        if client is None:
            return self.client
        return client

    def num_keys(self, db=0, client=None):
        if client is None:
            client = self.client
        if f"db{db}".format(db) in client.info("all").keys():
            return client.info("all")["db{}".format(db)]["keys"]
        return 0

    def is_primary_link_up(self, client=None):
        if client is None:
            client = self.client
        """Returns True if role is slave and master_link_status is up"""
        if (
            client.info(section="replication")["role"] == "slave"
            and client.info(section="replication")["master_link_status"] == "up"
        ):
            return True
        return False

    def _action_success_flag(self, action, client):
        if action == ValkeyAction.AOF_REWRITE:
            return client.info()["aof_last_bgrewrite_status"] == "ok"
        else:
            raise RuntimeError("{} not support".format(action))

    def wait_for_action_done(self, action, client=None):
        if client is None:
            client = self.client
        try:
            if action == ValkeyAction.AOF_REWRITE:
                wait_for_equal(
                    lambda: client.info()["aof_rewrite_in_progress"],
                    1,
                    timeout=TEST_MAX_WAIT_TIME_SECONDS,
                )
            else:
                raise RuntimeError("{} not support".format(action))
        except WaitTimeout:
            raise RuntimeError("{} failed to complete in time".format(action))
        assert self._action_success_flag(action, client)


class ValkeyTestCaseBase:
    testdir = "test-data"
    rdbdir = "rdbs"

    DEFAULT_BIND_IP = "0.0.0.0"

    @pytest.fixture(autouse=True)
    def port_tracker_fixture(self, resource_port_tracker):
        """
        port_tracker_fixture using resource_port_tracker.
        """
        # Inject port tracker
        logging.info("port tracker")
        self.args = {}
        self.port_tracker = resource_port_tracker

    def ensureDirExists(self, dir):
        if not os.path.isdir(self.testdir):
            try:
                os.mkdir(self.testdir)
            except:
                assert os.path.isdir(
                    self.testdir
                )  # If tests have conflicted with each other check again

    def findLogfileLine(self, filename, regex):
        try:
            logfile = open(filename, "r")
            for line in logfile:
                match = re.search(regex, line)
                if match:
                    return match
            return None
        except:
            return None

    def doesLogfileContain(self, filename, regex):
        return self.findLogfileLine(filename, regex) != None

    def wait_for_logfile(self, filename, regex):
        wait_for_true(
            lambda: self.doesLogfileContain(filename, regex),
            timeout=TEST_MAX_WAIT_TIME_SECONDS,
        )

    def check_all_keys_in_valkey(self, node, dictionary):
        """Check that all the keys in Valkey matches that in the dictionary"""
        num_keys_in_valkey = 0
        for key in node.client.scan_iter():
            if dictionary.keys():
                if isinstance(list(dictionary.keys())[0], str) and isinstance(
                    key, bytes
                ):
                    key = key.decode()

            assert node.client.get(key) == str.encode(dictionary[key])
            num_keys_in_valkey += 1
        return num_keys_in_valkey

    def waitForReplicaToSyncUp(self, server):
        wait_for_true(lambda: server.is_primary_link_up(), timeout=MAX_SYNC_WAIT)

    # Wait until a client in the Valkey is executing a command
    # Used to ensure that a thread running a blocking command has started
    # Return True if the command is running, False if timeout
    def wait_until_command(self, server, cmd):
        wait_seconds = 0
        while wait_seconds < TEST_MAX_WAIT_TIME_SECONDS:
            for client in server.client.client_list():
                if client["cmd"] == cmd:
                    return True
            time.sleep(1)
            wait_seconds += 1
        return False

    def get_bind_port(self):
        return self.port_tracker.get_unused_port()

    def get_bind_ip(self, multi_ip_mode=False):
        if multi_ip_mode:
            return self.ip_tracker.get_ip_address()
        return self.DEFAULT_BIND_IP


class ValkeyTestCase(ValkeyTestCaseBase):
    server_path = (
        "valkey-server"  # The default server build is assumed that valkey-server is set
    )

    def common_setup(self):
        self.port = self.port_tracker.get_unused_port()
        self.ensureDirExists(self.testdir)
        self.server_list = []

    @pytest.fixture(autouse=True)
    def setup(self, port_tracker_fixture):
        self.common_setup()
        yield

    def get_valkey_handle(self):
        """Return valkey node handle. Allow child class to override the handle type"""
        return ValkeyServerHandle

    # Expose bind_ip parameter to caller to have more flexible
    def create_server(
        self,
        testdir,
        bind_ip=None,
        port=None,
        server_path=server_path,
        args="",
        skip_teardown=False,
        conf_file=None,
        external_server=False,
        wait_for_ping=True,
        connect_client=True,
    ):

        if external_server:
            if not bind_ip:
                raise ValueError("Bind ip must be specified for external server use")
            if not port:
                raise ValueError("Port must be specified for external server use")

            valkey_server = ValkeyServerHandle(
                bind_ip, port, port_tracker=None, external_mode=True
            )

            valkey_server._test_instance = self
            valkey_cli = valkey_server.connect()

            if not skip_teardown:
                self.server_list.append(valkey_server)
            return valkey_server, valkey_cli

        if not bind_ip:
            bind_ip = self.get_bind_ip()

        if not port:
            port = self.get_bind_port()

        valkey_server_handle = self.get_valkey_handle()
        self.server_path = server_path
        valkey_server = valkey_server_handle(
            bind_ip=bind_ip,
            port=port,
            port_tracker=self.port_tracker,
            cwd=testdir,
            server_path=server_path,
        )
        if not skip_teardown:
            self.server_list.append(valkey_server)
        valkey_server.conf_file = conf_file
        valkey_server.args.update(args)
        valkey_cli = valkey_server.start(
            wait_for_ping=wait_for_ping, connect_client=connect_client
        )
        return valkey_server, valkey_cli

    def wait_for_all_replicas_online(self, n):
        wait_for_equal(
            lambda: self.server.num_replicas_online(), n, timeout=MAX_REPLICA_WAIT_TIME
        )

    def wait_for_replicas(self, n):
        self.server.wait_for_replicas(n)

    def teardown(self):
        for server in self.server_list:
            if server:
                server.exit()
                server = None


class ValkeyReplica(ValkeyServerHandle):
    def __init__(
        self,
        primaryhost,
        primaryport,
        bind_ip,
        port,
        port_tracker,
        testdir,
        server_path,
    ):
        super(ValkeyReplica, self).__init__(
            bind_ip, port, port_tracker, server_path, testdir
        )
        self.clients = []
        self.primaryhost = primaryhost
        self.primaryport = primaryport
        self.args["slaveof"] = self.primaryhost + " " + str(self.primaryport)

    def exit(self, remove_rdb=True, remove_nodes_conf=True):
        super(ValkeyReplica, self).exit(remove_rdb, remove_nodes_conf)
        del self.clients[:]


class ReplicationTestCase(ValkeyTestCase):
    num_replicas = 0
    skip_teardown = False
    replicas = []
    # Primary server
    server = None

    def setup_replication(
        self, num_replicas=1, primary_server=None, skip_teardown=False
    ):
        self.num_replicas = num_replicas
        self.replicas = []
        if primary_server is not None:
            self.server = primary_server
        self.skip_teardown = skip_teardown
        self.create_replicas(num_replicas)
        self.start_replicas()
        self.wait_for_replicas(self.num_replicas)
        self.wait_for_primary_link_up_all_replicas()
        self.wait_for_all_replicas_online(self.num_replicas)
        for i in range(len(self.replicas)):
            self.waitForReplicaToSyncUp(self.replicas[i])
        return self.replicas

    def teardown(self):
        if not self.skip_teardown:
            self.destroy_replicas()
            ValkeyTestCase.teardown(self)

    def _create_replica(self, primaryhost, primaryport, server_path):
        return ValkeyReplica(
            primaryhost,
            primaryport,
            self.get_bind_ip(),
            self.get_bind_port(),
            self.port_tracker,
            self.testdir,
            self.server_path,
        )

    def create_replicas(
        self,
        num_replicas,
        primaryhost=None,
        primaryport=None,
        connection_type="tcp",
        server_path=None,
    ):
        default_primaryhost = None
        default_port = None
        if connection_type == "tcp":
            if hasattr(self.server, "bind_ip"):
                default_primaryhost = self.server.bind_ip
            if hasattr(self.server, "port"):
                default_port = self.server.port
        elif connection_type == "unix":
            default_primaryhost = self.server.args["unixsocket"]
            default_port = 0  # Valkey treats the hostname as a unix socket path if the port is zero.
        else:
            raise ValueError(
                "Invalid connection type %r, expected 'tcp' or 'unix'" % connection_type
            )

        if not primaryhost:
            primaryhost = default_primaryhost

        if not primaryport:
            primaryport = default_port

        for _ in range(self.num_replicas):
            replica = self._create_replica(primaryhost, primaryport, server_path)
            replica.set_startup_args(self.args)
            self.replicas.append(replica)

    def start_replicas(self, wait_for_ping=True):
        for i in range(self.num_replicas):
            self.replicas[i].start(wait_for_ping=wait_for_ping)

    def destroy_replicas(self):
        try:
            for i in range(self.num_replicas):
                self.replicas[i].exit()
        except AttributeError:
            logging.info("this test was skipped. Nothing to destroy")
            return
        self.num_replicas = 0
        del self.replicas[:]

    def wait_for_primary_link_up_all_replicas(self):
        for i in range(self.num_replicas):
            wait_for_true(
                lambda: self.replicas[i].is_primary_link_up(), timeout=MAX_SYNC_WAIT
            )

    def wait_for_value_propagate_to_replicas(self, key, value, db=0):
        for i in range(self.num_replicas):
            wait_for_equal(
                lambda: self.replicas[i].clients[db].get(key),
                value,
                timeout=TEST_MAX_WAIT_TIME_SECONDS,
            )

    def waitForReplicaOffsetToSyncUp(self, primary, replica):
        pinfo = primary.info(section="replication")["master_repl_offset"]
        wait_for_equal(
            lambda: replica.client.info(section="replication")["slave_repl_offset"],
            pinfo.get_primary_repl_offset(),
            timeout=TEST_MAX_WAIT_TIME_SECONDS,
        )


from valkey.cluster import VALKEY_CLUSTER_HASH_SLOTS


class ClusterInfo:
    """Contains information about a point in time of a Valkey cluster."""

    def __init__(self, info):
        self.info = info

    def get_cluster_my_epoch(self):
        return self.info["cluster_my_epoch"]

    def get_cluster_epoch(self):
        return self.info["cluster_current_epoch"]

    def is_cluster_ok(self):
        """Return True if the cluster state is OK."""
        return self.info["cluster_state"] == "ok"

    def is_cluster_down(self):
        """Return True if the cluster state is fail."""
        return self.info["cluster_state"] == "fail"

    def cluster_known_nodes(self):
        """Return the number of nodes known to this node."""
        return int(self.info["cluster_known_nodes"])

    def cluster_slots_assigned(self):
        """Return the number of hash slots currently assigned."""
        return int(self.info["cluster_slots_assigned"])


class ClusterNodeHandle(ValkeyServerHandle):
    """Handle to a valkey server process running in cluster mode enabled (CME)."""

    def __init__(
        self,
        bind_ip,
        port,
        port_tracker,
        testdir,
        server_path="valkey-server",
    ):
        super(ClusterNodeHandle, self).__init__(
            bind_ip, port, port_tracker, server_path=server_path, cwd=testdir
        )
        # Start the node in cluster mode. The cluster-config-file (nodes.conf)
        # is per-node and cleaned up by the base class teardown.
        self.args["cluster-enabled"] = "yes"
        self.args["cluster-config-file"] = "nodes_{}_{}.conf".format(bind_ip, port)
        self.args["cluster-node-timeout"] = "2000"
        self.masterid = None
        self.nodeid = None

    def _set_node_id(self):
        # CLUSTER NODES should return only one node - myself after startup
        # Read the node id
        nodes = self.client.cluster("NODES")
        for key in nodes:
            if re.match("myself", nodes[key]["flags"]):
                self.nodeid = nodes[key]["node_id"]
                logging.info(
                    "Cluster node {} has node id {}".format(self.port, self.nodeid)
                )
                return

    def start(self, connect_client=True):
        super(ClusterNodeHandle, self).start(connect_client=connect_client)
        if connect_client:
            self._set_node_id()

    def connect(self):
        client = super(ClusterNodeHandle, self).connect()
        self._set_node_id()
        return client

    def meet(self, ip, port):
        return self.client.execute_command("CLUSTER", "MEET", ip, port)

    def replicate(self, node_id):
        self.masterid = node_id
        return self.client.execute_command("CLUSTER", "REPLICATE", node_id)

    def assign_slots(self, *args):
        """
        Assign multiple ranges of slots to this node.
        Accepts multiple pairs that are interpretted as [low,high)
        assign_slots(0,10) -> [0..9]
        assign_slots(0,10,15,20) -> [0..9] and [15..19]
        """
        assert len(args) % 2 == 0
        command = ["CLUSTER", "ADDSLOTSRANGE"]
        for t in range(0, len(args), 2):
            command.extend([args[t], args[t + 1] - 1])
        return self.client.execute_command(*command)

    def wait_for_cluster_known_nodes(self, count):
        """Wait until we are connected to exactly count nodes."""
        wait_for_equal(
            lambda: ClusterInfo(self.client.cluster("INFO")).cluster_known_nodes(),
            count,
            timeout=TEST_MAX_WAIT_TIME_SECONDS,
        )

    def wait_for_cluster_know_node(self, nodeid):
        def knows():
            nodesInfo = self.client.cluster("NODES")
            for key in nodesInfo:
                if re.match(nodeid, nodesInfo[key]["node_id"]):
                    return True
            return False

        wait_for_true(knows, timeout=TEST_MAX_WAIT_TIME_SECONDS)

    def wait_for_cluster_ok(self):
        wait_for_true(
            lambda: ClusterInfo(self.client.cluster("INFO")).is_cluster_ok(),
            timeout=TEST_MAX_WAIT_TIME_SECONDS,
        )


class ClusterTestCase(ValkeyTestCase):
    """Base class for Cluster Mode Enabled (CME) tests."""

    @pytest.fixture(autouse=True)
    def cluster_setup(self):
        # Per-test cluster state. Initialized here rather than as class-level
        # attributes so each test starts with its own node list.
        self.nodes = []
        self.cluster_client = None
        yield
        self.teardown()

    def create_node(self, bind_ip=None, port=None):
        """Create a single cluster-mode node and register it for teardown."""
        if not bind_ip:
            bind_ip = self.get_bind_ip()
        if not port:
            port = self.get_bind_port()

        node = ClusterNodeHandle(
            bind_ip=bind_ip,
            port=port,
            port_tracker=self.port_tracker,
            testdir=self.testdir,
            server_path=self.server_path,
        )
        node.args.update(self.args)
        self.nodes.append(node)
        # Registered in server_list so ValkeyTestCase.teardown reclaims it.
        self.server_list.append(node)
        return node

    def create_nodes(self, num_nodes):
        for _ in range(num_nodes):
            self.create_node()
        return self.nodes

    def start_all_nodes(self):
        for node in self.nodes:
            node.start()

    def create_cluster(self, num_nodes):
        """Start `num_nodes` nodes and gossip them into a single cluster."""
        self.create_nodes(num_nodes)
        self.start_all_nodes()

        # Introduce every other node to the first node; gossip propagates the
        # full topology from there.
        for i in range(1, num_nodes):
            self.nodes[0].meet(self.nodes[i].bind_ip, self.nodes[i].port)

        # Wait until every node has discovered the whole cluster.
        for node in self.nodes:
            node.wait_for_cluster_known_nodes(num_nodes)

    def assign_slots_to_nodes(self, num_nodes):
        slot_slice = VALKEY_CLUSTER_HASH_SLOTS / num_nodes
        for i in range(num_nodes):
            slot_min = int(round(slot_slice * i))
            slot_max = int(round(slot_slice * (i + 1)))
            self.nodes[i].assign_slots(slot_min, slot_max)

    def setup_replicas(self, num_shards, num_replicas_per_shard):
        """Attach the remaining nodes as replicas, round-robin across shards."""
        total = num_shards * (1 + num_replicas_per_shard)
        for i in range(num_shards, total):
            shard_idx = i % num_shards
            primary = self.nodes[shard_idx]
            # Make sure the replica knows the primary before replicating.
            self.nodes[i].wait_for_cluster_know_node(primary.nodeid)
            self.nodes[i].replicate(primary.nodeid)

        # Wait for each shard's replicas to come online and sync up.
        for i in range(num_shards):
            wait_for_equal(
                lambda primary=self.nodes[i]: primary.num_replicas_online(),
                num_replicas_per_shard,
                timeout=MAX_REPLICA_WAIT_TIME,
            )
        for i in range(num_shards, total):
            self.waitForReplicaToSyncUp(self.nodes[i])
            # Allow read-only queries to be served by the replica.
            try:
                self.nodes[i].client.readonly()
            except Exception:
                logging.warning(
                    "READONLY failed on replica port {}".format(self.nodes[i].port)
                )

    def setup_cluster(self, num_shards, num_replicas_per_shard):
        """Create and fully bootstrap a cluster, returning a cluster client.

        When this returns the cluster is in the 'ok' state and ready to serve.
        """
        total_nodes = num_shards * (1 + num_replicas_per_shard)
        self.create_cluster(total_nodes)

        self.assign_slots_to_nodes(num_shards)

        # Bump each primary's config epoch so replicas don't overtake it via
        # epoch collision resolution.
        for i in range(num_shards):
            self.nodes[i].client.execute_command("CLUSTER", "BUMPEPOCH")

        if num_replicas_per_shard > 0:
            self.setup_replicas(num_shards, num_replicas_per_shard)

        # Wait for every node to agree the cluster is healthy.
        for node in self.nodes:
            node.wait_for_cluster_ok()

        self.cluster_client = self.get_cluster_client()
        return self.cluster_client

    def get_cluster_client(self):
        """Return a cluster-aware client that follows MOVED/ASK redirections."""
        from valkey.cluster import ValkeyCluster

        primary = self.nodes[0]
        # A cluster client discovers the topology by connecting to the host each
        # node advertises in CLUSTER SLOTS, not the bind address. When a node
        # binds the wildcard 0.0.0.0 it advertises a concrete, connectable host
        # (typically loopback) instead, so read that advertised host back and
        # seed the client with it rather than the bind address.
        host = primary.bind_ip
        for slot_range in primary.client.cluster("SLOTS"):
            # slot_range = [start, end, [host, port, node_id, ...], ...]
            owner_host, _, owner_id = (
                slot_range[2][0],
                slot_range[2][1],
                slot_range[2][2],
            )
            if owner_id.decode() == primary.nodeid:
                host = owner_host.decode()
                break
        return ValkeyCluster(host=host, port=primary.port)

    def teardown(self):
        if self.cluster_client is not None:
            try:
                self.cluster_client.close()
            except Exception:
                pass
            self.cluster_client = None
        ValkeyTestCase.teardown(self)
