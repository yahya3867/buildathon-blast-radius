import gzip
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", "/data"))
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")

NONE_CHECK = re.compile(r"\bself\.(\w+) (is not|is|!=|==) None\b")
POLARITY = {"is": True, "==": True, "is not": False, "!=": False}

def equivalent_none_check(old, new, number, declarations):
    left, right = NONE_CHECK.search(old), NONE_CHECK.search(new)
    if not left or not right or left[1] != right[1] or POLARITY[left[2]] != POLARITY[right[2]]:
        return False
    if old[:left.start()] != new[:right.start()] or old[left.end():] != new[right.end():]:
        return False
    return any(begin <= number <= end and left[1] in fields for begin, end, fields in declarations)

def affected(patch, coverage, tests, field_types):
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
    rows = iter(patch.splitlines())
    pending = next(rows, None)
    while pending is not None:
        row, pending = pending, next(rows, None)
        if row.startswith("-") and not row.startswith("---") and pending and pending.startswith("+") and equivalent_none_check(
                row[1:], pending[1:], line, field_types.get(file, ())):
            flush()
            line += 1
            pending = next(rows, None)
            continue
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
    with gzip.open(HERE / "fields.json.gz", "rt") as src:
        field_types = json.load(src)
    catalog = {t["id"]: t for t in json.loads((DATA / "tests.json").read_text())["tests"]}
    for patch in sorted((DATA / "commits").glob("*.patch")):
        bits = affected(patch.read_text(encoding="utf-8"), coverage, tests, field_types)
        chosen = [catalog[t] for i,t in enumerate(tests) if bits & (1 << i) and t in catalog]
        print(json.dumps({"commit":patch.stem, "workers":schedule(chosen)}, separators=(",",":")))

if __name__ == "__main__":
    main()
