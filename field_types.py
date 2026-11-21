"""Extract declared instance-field types and identity equality from the pinned Python sources."""
import ast
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

def type_names(node):
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return type_names(node.left) + type_names(node.right)
    if isinstance(node, ast.Constant) and node.value is None:
        return ["None"]
    if isinstance(node, ast.Name):
        return [node.id]
    return ["?"]

def main(root, output):
    classes = defaultdict(list)
    children = defaultdict(list)
    by_file = defaultdict(list)
    bindings = defaultdict(dict)
    qualified = {}
    for path in (root / "sqlglot").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        tree=ast.parse(path.read_bytes())
        module=".".join(path.relative_to(root).with_suffix("").parts)
        for imp in ast.walk(tree):
            if isinstance(imp,ast.ImportFrom) and imp.module and not imp.level:
                for item in imp.names:
                    bindings[rel][item.asname or item.name]=imp.module+"."+item.name
        for obj in tree.body:
            if not isinstance(obj, ast.ClassDef):
                continue
            classes[obj.name].append(obj)
            qualified[module+"."+obj.name]=obj
            bindings[rel][obj.name]=module+"."+obj.name
            for base in obj.bases:
                children[ast.unparse(base).split(".")[-1]].append(obj)
            by_file[rel].append(obj)

    def plain(node):
        return not node.decorator_list and not node.keywords and not any(
            isinstance(n, (ast.FunctionDef, ast.Assign)) and
            (n.name if isinstance(n, ast.FunctionDef) else ast.unparse(n.targets[0])) in ("__eq__", "__ne__")
            for n in node.body)

    def vanilla_subclasses(name, visited):
        if name in visited:
            return False
        return all(plain(sub) and len(sub.bases)==1 and vanilla_subclasses(sub.name, visited | {name})
                   for sub in children[name])

    safe = {name for name, nodes in classes.items() if len(nodes)==1 and not nodes[0].bases
            and plain(nodes[0]) and vanilla_subclasses(name, set())}
    safe.update(("str","int","bool","float","bytes","None"))
    safe_qualified={k for k, node in qualified.items() if not node.bases and plain(node) and vanilla_subclasses(node.name,set())}
    records = {}
    for rel, nodes in by_file.items():
        for obj in nodes:
            fields = {}
            for method in obj.body:
                if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                    for ann in ast.walk(method):
                        if isinstance(ann, ast.AnnAssign) and isinstance(ann.target, ast.Attribute) and ast.unparse(ann.target.value)=="self":
                            names = type_names(ann.annotation)
                            if all((bindings[rel][n] in safe_qualified if n in bindings[rel] else n in safe) for n in names):
                                fields[ann.target.attr]=names
            if fields:
                records.setdefault(rel, []).append([obj.lineno, obj.end_lineno, fields])
    with gzip.open(output, "wt") as f:
        json.dump(records,f,separators=(",",":"))

if __name__=="__main__":
    main(Path(sys.argv[1]),sys.argv[2])
