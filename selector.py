import gzip
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", "/data"))
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")

def affected(patch, coverage, tests):
    selected = 0
    file = ""
    line = 0
    added = removed = False
    changed = set()
    def flush():
        nonlocal added, removed, selected
        if added and not removed:
            changed.update([line - 1, line])
        lines = coverage.get(file, {})
        for n in changed:
            selected |= int(lines.get(str(n), "0"), 16)
        if changed and "0" in lines:
            selected |= int(lines["0"], 16)
        if changed and file.startswith("tests/") and file.endswith(".py"):
            for i, name in enumerate(tests):
                if name.partition("::")[0] == file:
                    selected |= 1 << i
        changed.clear()
        added = removed = False
    for row in patch.splitlines():
        if row.startswith("diff --git "):
            flush()
            file = row.partition(" b/")[2]
        elif row.startswith(("+++ ", "--- ")):
            continue
        elif match := HUNK.match(row):
            flush()
            line = int(match[1])
        elif row.startswith("-"):
            changed.add(line)
            # Changing a short-circuit connector can execute a branch that was
            # skipped in the base checkout. Include its preceding condition.
            if row[1:].lstrip().startswith(("and ", "or ")):
                changed.update(range(max(1,line-3),line))
            removed = True
            line += 1
        elif row.startswith("+"):
            added = True
        elif row.startswith(" "):
            flush()
            line += 1
    flush()
    return selected

def schedule(chosen):
    if not chosen:
        return []
    ordered = sorted(chosen, key=lambda t: -t["seconds"])
    best = float("inf")
    for count in range(1, min(8, len(ordered)) + 1):
        loads = [0.0] * count
        workers = [[] for _ in loads]
        for test in ordered:
            index = loads.index(min(loads))
            workers[index].append(test["number"])
            loads[index] += test["seconds"]
        cost = max(loads) + 2 * count
        if cost < best:
            best, result = cost, workers
    return result

def main():
    with gzip.open(HERE / "map.json.gz", "rt") as src:
        tests, coverage = json.load(src)
    catalog = {t["id"]: t for t in json.loads((DATA / "tests.json").read_text())["tests"]}
    for patch in sorted((DATA / "commits").glob("*.patch")):
        bits = affected(patch.read_text(encoding="utf-8"), coverage, tests)
        chosen = [catalog[t] for i,t in enumerate(tests) if bits & (1 << i) and t in catalog]
        print(json.dumps({"commit":patch.stem, "workers":schedule(chosen)}, separators=(",",":")))

if __name__ == "__main__":
    main()
