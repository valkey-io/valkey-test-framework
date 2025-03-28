from util.waiters import *


class TestWaiters:
    def test_wait_for_equal(self):
        counter = 0

        def increment_counter():
            nonlocal counter
            counter += 1
            return counter

        wait_for_equal(lambda: increment_counter(), 10)
        assert counter == 10

    def test_wait_for_true(self):
        flag = False

        def set_flag_true():
            nonlocal flag
            if not flag:
                flag = True
            return flag

        wait_for_true(lambda: set_flag_true())
        assert flag == True

    def test_wait_for_false(self):
        flag = True

        def set_flag_false():
            nonlocal flag
            if flag:
                flag = False
            return flag

        wait_for_false(lambda: set_flag_false())
        assert flag == False

    def test_wait_for_ne(self):
        value = 0

        def increment_value():
            nonlocal value
            value += 1
            return value

        wait_for_ne(lambda: increment_value(), 0)
        assert value != 0
