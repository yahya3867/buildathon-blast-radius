"""Index executable references to import-time constants in the pinned checkout."""
import ast
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

root, coverage_file, output = map(Path, sys.argv[1:])
tests, coverage = json.load(gzip.open(coverage_file, "rt"))
definitions, readers = defaultdict(list), defaultdict(int)
for path in (root / "sqlglot").rglob("*.py"):
    relative = path.relative_to(root).as_posix()
    lines = coverage.get(relative, {})
    tree = ast.parse(path.read_bytes(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name) and target.id.isupper():
                    definitions[target.id].append((relative, node.lineno))
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name.isupper():
                readers[name] |= int(lines.get(str(node.lineno), "0"), 16)
for name, locations in definitions.items():
    for path, line in locations:
        if readers[name]:
            lines = coverage.setdefault(path, {})
            lines[str(line)] = format(readers[name] | int(lines.get(str(line),"0"),16), "x")
with gzip.open(output, "wt") as dst:
    json.dump([tests,coverage],dst,separators=(",",":"))
