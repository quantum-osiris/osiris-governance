"""Minimal pytest shim for test file imports in standard environments."""

class RaisesContext:
    def __init__(self, expected_exc):
        self.expected_exc = expected_exc
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected exception {self.expected_exc.__name__} was not raised")
        if issubclass(exc_type, self.expected_exc):
            self.value = exc_val
            return True
        return False


def raises(expected_exc):
    return RaisesContext(expected_exc)


def fixture(func):
    return func
