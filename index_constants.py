"""Extend the pinned checkout's line coverage to declarations read during tests."""
import ast
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

def impact_index(root, coverage):
    readers = defaultdict(int)
    definitions = []
    dialect_usage = defaultdict(int)
    for path in sorted((root / "sqlglot").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        lines = coverage.get(rel, {})
        tree = ast.parse(path.read_bytes(), filename=rel)
        # Header/decorator changes affect callers even though the definition
        # executed before pytest began recording any per-test line coverage.
        original = dict(lines)
        for method in ast.walk(tree):
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or not method.body:
                continue
            entry_tests = 0
            for n in range(method.body[0].lineno, method.end_lineno + 1):
                entry_tests |= int(original.get(str(n), "0"), 16)
            if entry_tests:
                begin = min([method.lineno] + [d.lineno for d in method.decorator_list])
                for n in range(begin, min(method.body[0].lineno, method.end_lineno + 1)):
                    key = str(n)
                    lines[key] = format(int(lines.get(key,"0"),16) | entry_tests,"x")
        if path.parent.name in ("dialects", "generators", "parsers", "typing"):
            for bits in lines.values():
                dialect_usage[path.stem] |= int(bits, 16)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        definitions.append((path, rel, node, target.id))
            if isinstance(node, (ast.Attribute, ast.Name)) and isinstance(node.ctx, ast.Load):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name.isupper():
                    readers[name] |= int(lines.get(str(node.lineno), "0"), 16)
    for path, rel, node, name in definitions:
        bits = readers[name]
        if path.parent.name == "dialects" and path.stem != "dialect":
            family = dialect_usage[path.stem]
            if family and bits:
                bits &= family
        if bits:
            lines = coverage.setdefault(rel, {})
            for number in range(node.lineno, node.end_lineno + 1):
                key = str(number)
                lines[key] = format(bits | int(lines.get(key, "0"), 16), "x")

def main():
    root, coverage_file, output = map(Path, sys.argv[1:])
    with gzip.open(coverage_file, "rt") as src:
        tests, coverage = json.load(src)
    impact_index(root, coverage)
    with gzip.open(output, "wt") as dest:
        json.dump([tests, coverage], dest, separators=(",", ":"))

if __name__ == "__main__":
    main()
