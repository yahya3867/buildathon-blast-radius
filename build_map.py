"""Build a test-to-source coverage index on the pinned, unmodified checkout."""
import gzip
import json
import sys
from pathlib import Path
import pytest

root = Path.cwd()
prefix = str(root) + str(Path("/"))
files = {}
hits = {}
active = None
tests = []


def line(code, number):
    filename = code.co_filename
    if filename not in files:
        try:
            relative = Path(filename).relative_to(root).as_posix()
        except ValueError:
            relative = ""
        files[filename] = relative if relative.startswith(("sqlglot/", "tests/")) else ""
    if active is not None and files[filename]:
        active.add((files[filename], number))
    return sys.monitoring.DISABLE


def opened(event, args):
    if active is None or event != "open" or not isinstance(args[0], str):
        return
    path = args[0].replace("\\", "/")
    if "/tests/fixtures/" in path:
        active.add(("tests/fixtures/" + path.split("/tests/fixtures/", 1)[1], 0))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    global active
    active = set()
    sys.monitoring.restart_events()
    yield
    covered, active = active, None
    idx = len(tests)
    tests.append(item.nodeid)
    for key in covered:
        hits[key] = hits.get(key, 0) | (1 << idx)


def main():
    import os
    import concurrent.futures
    import pickle

    # Replay worker calls in the traced interpreter. Round-trip arguments and
    # return values so serialization code is measured too.
    class TracedPool(concurrent.futures.Executor):
        def __init__(self, *args, **kwargs):
            if initializer := kwargs.get("initializer"):
                initializer(*kwargs.get("initargs", ()))

        def submit(self, fn, /, *args, **kwargs):
            future = concurrent.futures.Future()
            try:
                func, a, kw = pickle.loads(pickle.dumps((fn, args, kwargs)))
                future.set_result(pickle.loads(pickle.dumps(func(*a, **kw))))
            except Exception as error:
                future.set_exception(error)
            return future

    concurrent.futures.ProcessPoolExecutor = TracedPool
    os.environ["SKIP_INTEGRATION"] = "0"
    sys.path.insert(0, str(root))
    sys.addaudithook(opened)
    mon = sys.monitoring
    mon.use_tool_id(4, "coverage map")
    mon.register_callback(4, mon.events.LINE, line)
    mon.set_events(4, mon.events.LINE)
    status = pytest.main(["-q", "tests", "--disable-warnings"], plugins=[sys.modules[__name__]])
    if status not in (0, 1) or not tests:
        raise SystemExit(status or 1)
    index = {}
    for (path, number), bits in hits.items():
        index.setdefault(path, {})[number] = format(bits, "x")
    with gzip.open(sys.argv[1], "wt") as out:
        json.dump([tests, index], out, separators=(",", ":"))


if __name__ == "__main__":
    main()
