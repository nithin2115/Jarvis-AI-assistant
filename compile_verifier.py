"""Compile verifier for DSA / code generation outputs.

Deterministic, fail-safe gate that checks code blocks for the most common
compile-breaking errors. Returns (ok, reason). If the answer contains no
real code block, it passes (conceptual answers are not gate-checked).

Supported languages: python, java, cpp/c++.
"""
import re
import ast
import logging

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)


# Java common types that require an import (java.lang is implicitly imported).
_JAVA_IMPORT_TYPES = {
    "Scanner", "ArrayList", "LinkedList", "HashMap", "HashSet", "TreeMap",
    "TreeSet", "Map", "List", "Set", "Queue", "Deque", "PriorityQueue",
    "Stack", "Arrays", "Collections", "StringBuilder", "BufferedReader",
    "InputStreamReader", "Stream", "Optional", "AtomicInteger", "AtomicLong",
    "BigInteger", "BigDecimal", "Comparable", "Comparator", "Iterator",
    "Iterable", "Objects", "Math"  # java.lang.Math is auto-imported; harmless
}

# Java types that are in java.lang and do NOT need an import.
_JAVA_LANG_TYPES = {
    "String", "Integer", "Long", "Double", "Float", "Boolean", "Character",
    "Byte", "Short", "Void", "Object", "Class", "System", "Throwable",
    "Exception", "RuntimeException", "Error", "Math", "Thread", "Runnable",
    "StringBuilder", "StringBuffer", "CharSequence", "Comparable", "Iterable",
    "Enum"
}

# Common JDK classes that may be instantiated without tripping the existing
# import heuristic. Used ONLY by the undefined-class detector (false-positive guard).
_JDK_COMMON = {
    "Random", "Optional", "OptionalInt", "OptionalLong", "OptionalDouble",
    "Collectors", "Stream", "IntStream", "LongStream", "DoubleStream",
    "Pattern", "Matcher", "BigInteger", "BigDecimal", "StringBuilder",
    "StringBuffer", "StringJoiner", "Thread", "Runnable", "Object", "Number",
    "ArrayDeque", "LinkedHashMap", "LinkedHashSet", "Vector", "Hashtable",
    "BitSet", "Stack", "PriorityQueue", "ArrayList", "LinkedList", "HashMap",
    "HashSet", "TreeMap", "TreeSet", "Scanner", "Arrays", "Collections",
    "Comparator", "AbstractMap", "SimpleEntry", "Entry", "Pair", "Tuple",
    "Iterator", "ListIterator", "Exception", "RuntimeException", "Error",
    "Throwable", "IllegalArgumentException", "IllegalStateException",
    "NullPointerException", "IndexOutOfBoundsException", "NoSuchElementException",
    "UnsupportedOperationException", "Comparable", "Iterable", "Deque", "Queue",
    "List", "Set", "Map", "Collection", "SortedMap", "SortedSet", "NavigableMap",
    "NavigableSet", "AtomicInteger", "AtomicLong", "AtomicBoolean",
    "AtomicReference", "ConcurrentHashMap", "ReentrantLock", "CountDownLatch",
    "Semaphore", "Future", "CompletableFuture", "Executors", "ExecutorService",
}

# Python builtin names that are commonly used without import.
_PYTHON_BUILTINS = {
    "abs", "all", "any", "ascii", "bin", "bool", "breakpoint", "bytearray",
    "bytes", "callable", "chr", "classmethod", "compile", "complex",
    "delattr", "dict", "dir", "divmod", "enumerate", "eval", "exec",
    "filter", "float", "format", "frozenset", "getattr", "globals",
    "hasattr", "hash", "help", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max", "memoryview",
    "min", "next", "object", "oct", "open", "ord", "pow", "print", "property",
    "range", "repr", "reversed", "round", "set", "setattr", "slice",
    "sorted", "staticmethod", "str", "sum", "super", "tuple", "type",
    "vars", "zip", "__import__", "True", "False", "None",
}

# Common Python modules that need an import when their top-level name is used.
_PYTHON_IMPORT_NAMES = {
    "collections", "heapq", "bisect", "itertools", "functools", "math",
    "random", "statistics", "re", "json", "sys", "os", "typing", "queue",
    "threading", "multiprocessing", "dataclasses", "enum", "inspect",
    "textwrap", "copy", "datetime", "decimal", "fractions", "array",
    "numbers", "pathlib", "string", "hashlib", "base64", "csv",
    "unittest", "pytest", "numpy", "pandas",
}

# C++ common headers required by symbols. We only check a few obvious ones.
_CPP_HEADER_NEEDS = {
    "cout": "iostream", "cin": "iostream", "endl": "iostream",
    "vector": "vector", "map": "map", "unordered_map": "unordered_map",
    "set": "set", "unordered_set": "unordered_set", "queue": "queue",
    "priority_queue": "queue", "stack": "stack", "deque": "deque",
    "list": "list", "string": "string", "sort": "algorithm",
    "lower_bound": "algorithm", "upper_bound": "algorithm",
    "binary_search": "algorithm", "unique": "algorithm", "reverse": "algorithm",
    "accumulate": "numeric", "numeric_limits": "limits", "std::thread": "thread",
    "mutex": "mutex", "lock_guard": "mutex",
}


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------
def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return [(lang, code), ...] for fenced code blocks."""
    out = []
    for m in _FENCE_RE.finditer(text or ""):
        lang = (m.group(1) or "").strip().lower()
        code = m.group(2) or ""
        out.append((lang, code))
    return out


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
def _python_check_syntax(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
    except SyntaxError as e:
        if "indent" in e.msg.lower():
            return False, f"Python indentation error: {e.msg} (line {e.lineno})."
        return False, f"Python syntax error: {e.msg} (line {e.lineno})."
    except Exception as e:
        return False, f"Python parse error: {e}."
    try:
        compile(code, "<string>", "exec")
    except IndentationError as e:
        return False, f"Python indentation error: {e.msg} (line {e.lineno})."
    except SyntaxError as e:
        return False, f"Python compile error: {e.msg} (line {e.lineno})."
    return True, ""


def _python_check_imports(code: str) -> tuple[bool, str]:
    """Best-effort check for obviously missing imports (low false-positive)."""
    try:
        tree = ast.parse(code)
    except Exception:
        return True, ""

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imports.add(alias.asname or alias.name)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

    # Names used at module level (excluding local function names)
    global_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                global_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and isinstance(node.value.ctx, ast.Load):
                global_names.add(node.value.id)

    missing = []
    for name in sorted(global_names):
        if name in _PYTHON_BUILTINS:
            continue
        if name in imports:
            continue
        if name in _PYTHON_IMPORT_NAMES:
            missing.append(name)

    if missing:
        return False, (
            "Python code uses the following module names without importing them: "
            f"{', '.join(missing)}. Add `import {missing[0]}` (and the rest)."
        )
    return True, ""


def _walk_no_nested_class(node):
    """Yield all descendants of node EXCEPT subtrees rooted at a nested ClassDef,
    so a nested class's `self` references aren't attributed to the outer class."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            continue
        yield child
        yield from _walk_no_nested_class(child)


def _python_undefined_self_attrs(code: str) -> tuple[bool, str]:
    """Reject reads of `self.X` that are never assigned anywhere in the class
    (catches the node.prev-style 'attribute used but not declared' compile bug).

    Conservative: classes that inherit (non-object base), use a metaclass, or use
    dynamic attribute access (setattr/getattr/__dict__ on self) are skipped, and
    dunder/name-mangled attributes are ignored."""
    try:
        tree = ast.parse(code)
    except Exception:
        return True, ""  # syntax errors handled elsewhere

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        if any(not (isinstance(b, ast.Name) and b.id == "object") for b in cls.bases):
            continue  # inherits unknown members
        if cls.keywords:
            continue  # metaclass / dynamic base

        declared = set()
        for stmt in cls.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                declared.add(stmt.name)
            elif isinstance(stmt, ast.Assign):
                declared.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                declared.add(stmt.target.id)

        dynamic = False
        loads = []
        for n in _walk_no_nested_class(cls):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and \
                    n.func.id in ("setattr", "getattr", "hasattr", "delattr", "vars"):
                if n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "self":
                    dynamic = True
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and \
                    n.value.id == "self":
                if n.attr == "__dict__":
                    dynamic = True
                elif isinstance(n.ctx, ast.Store):
                    declared.add(n.attr)
                elif isinstance(n.ctx, ast.Load):
                    loads.append(n.attr)
        if dynamic:
            continue

        for attr in loads:
            if attr.startswith("__"):
                continue  # dunder / name-mangled
            if attr not in declared:
                return False, (
                    f"references 'self.{attr}' which is never assigned in class "
                    f"'{cls.name}'. Define the '{attr}' attribute (e.g. in __init__) "
                    "or fix the reference."
                )
    return True, ""


def check_python(code: str) -> tuple[bool, str]:
    ok, reason = _python_check_syntax(code)
    if not ok:
        return ok, reason
    ok, reason = _python_check_imports(code)
    if not ok:
        return ok, reason
    ok, reason = _python_undefined_self_attrs(code)
    if not ok:
        return ok, reason
    return True, ""


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------
def _java_public_classes(code: str) -> list[str]:
    return re.findall(r"\bpublic\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\b", code)


def _java_balanced_braces(code: str) -> tuple[bool, str]:
    # Strip comments and strings before counting braces.
    cleaned = re.sub(r"//.*?$", "", code, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'"(?:\\"|[^"])*"', '""', cleaned)
    cleaned = re.sub(r"'(?:\\'|[^'])*'", "''", cleaned)
    opens = cleaned.count("{")
    closes = cleaned.count("}")
    if opens != closes:
        return False, f"Unbalanced braces (open={opens}, close={closes})."
    parens_open = cleaned.count("(")
    parens_close = cleaned.count(")")
    if parens_open != parens_close:
        return False, f"Unbalanced parentheses (open={parens_open}, close={parens_close})."
    return True, ""


def _java_invalid_declarations(code: str) -> tuple[bool, str]:
    # public class without a name or empty body
    if re.search(r"\bpublic\s+class\s*\{", code):
        return False, "Invalid class declaration: `public class` has no class name."
    if re.search(r"\bclass\s*\{", code):
        return False, "Invalid class declaration: `class` has no class name."
    # standalone `public class` without a name: next non-whitespace char is not a word char.
    if re.search(r"\bpublic\s+class\b(?!\s*\w)", code):
        return False, "Malformed `public class` declaration: missing class name."
    return True, ""


def _java_method_returns(code: str) -> tuple[bool, str]:
    """Check non-void methods for at least one return statement.

    Heuristic: if a method is declared with a return type other than void,
    it must contain a `return` statement at the top level of its body.
    """
    # Remove nested code blocks to count only top-level returns per method.
    pattern = re.compile(
        r"\b(public\s+|private\s+|protected\s+|static\s+|final\s+)*"
        r"(?P<type>[A-Za-z_][A-Za-z0-9_<>\[\]\?\s,]*)\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{",
        re.DOTALL,
    )
    for m in pattern.finditer(code):
        ret_type = m.group("type").strip()
        if ret_type in ("void", "new"):
            continue
        # A bare modifier captured as the "type" means this is a constructor
        # (e.g. `public Foo(...) {`), which has no return type — never flag it.
        if ret_type in ("public", "private", "protected", "static", "final",
                         "abstract", "synchronized", "native", "default"):
            continue
        if "=" in ret_type or "(" in ret_type or ")" in ret_type:
            continue
        # Find the matching closing brace.
        start = m.end()
        depth = 1
        i = start
        while i < len(code) and depth > 0:
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
            i += 1
        body = code[start : i - 1]
        if not re.search(r"\breturn\b", body):
            return False, (
                f"Method `{m.group('name')}` returns `{ret_type}` but has no "
                "return statement."
            )
    return True, ""


def _java_imports(code: str) -> tuple[bool, str]:
    """Check for missing imports for common java.util types."""
    imports = set(re.findall(r"import\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", code))
    package = re.search(r"\bpackage\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", code)
    if package:
        # If a package is declared, we don't do heuristic import checks.
        return True, ""
    missing = []
    for typ in _JAVA_IMPORT_TYPES:
        if re.search(rf"\b{re.escape(typ)}\b", code) and typ not in _JAVA_LANG_TYPES:
            # Check if it is imported or fully qualified
            if not any(imp.endswith(f".{typ}") or imp == typ for imp in imports):
                if not re.search(rf"\bjava\.\w+\.{re.escape(typ)}\b", code):
                    missing.append(typ)
    if missing:
        return False, (
            "Java code uses the following types without importing them: "
            f"{', '.join(missing)}. Add the required `import java.util.*` statements."
        )
    return True, ""


# Keywords that may follow a class name but are NOT variable declarations.
_JAVA_KEYWORDS = {
    "extends", "implements", "return", "new", "instanceof", "class", "this",
    "super", "throws", "throw",
}

_JAVA_CLASS_HEADER_RE = re.compile(
    r"\b(?:public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+)*"
    r"class\s+([A-Za-z_]\w*)([^\{]*)\{"
)

# A field declaration at class-body level: `[modifiers] Type name[, name2] [= ...];`
_JAVA_FIELD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final|volatile|transient)\s+)*"
    r"[A-Za-z_][\w.]*(?:\s*<[^>]*>)?(?:\s*\[\s*\])*\s+"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*(?:=.*)?$",
    re.DOTALL,
)

# A member access `obj.member` whose obj is a bare identifier (not a chained call).
_JAVA_MEMBER_ACCESS_RE = re.compile(r"(?<![.\w])([A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)\s*(\()?")


def _strip_java_noise(code: str) -> str:
    """Remove comments and string/char literals so tokens inside them aren't matched."""
    cleaned = re.sub(r"//.*?$", "", code, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'"(?:\\.|[^"\\])*"', '""', cleaned)
    cleaned = re.sub(r"'(?:\\.|[^'\\])*'", "''", cleaned)
    return cleaned


def _extract_field_names(seg: str, fields: set) -> None:
    seg = seg.strip()
    if not seg or re.match(r"(?:@|class\b|interface\b|enum\b)", seg):
        return
    m = _JAVA_FIELD_RE.match(seg)
    if not m:
        return
    for nm in m.group(1).split(","):
        nm = nm.strip()
        if nm:
            fields.add(nm)


def _members_of_body(body: str) -> tuple[set, set]:
    """Return (fields, methods) declared at the TOP level of a class body (depth 0),
    skipping anything nested inside method/initializer/inner-class bodies (depth > 0)."""
    fields, methods = set(), set()
    depth = 0
    buf = []
    for c in body:
        if c == "{":
            if depth == 0:
                seg = "".join(buf)
                mm = re.search(r"([A-Za-z_]\w*)\s*\([^()]*\)\s*$", seg)
                if mm:
                    methods.add(mm.group(1))
                else:
                    _extract_field_names(seg, fields)
            depth += 1
            buf = []
        elif c == "}":
            depth = max(0, depth - 1)
            buf = []
        elif c == ";":
            if depth == 0:
                _extract_field_names("".join(buf), fields)
            buf = []
        elif depth == 0:
            buf.append(c)
    return fields, methods


def _java_class_members(code: str) -> dict:
    """Return {ClassName: {"fields", "methods", "inherits", "body"}} for declared classes."""
    cleaned = _strip_java_noise(code)
    classes = {}
    for m in _JAVA_CLASS_HEADER_RE.finditer(cleaned):
        name = m.group(1)
        inherits = bool(re.search(r"\b(?:extends|implements)\b", m.group(2) or ""))
        open_idx = m.end() - 1  # index of '{'
        depth, i, n = 0, open_idx, len(cleaned)
        while i < n:
            ch = cleaned[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = cleaned[open_idx + 1:i]
        fields, methods = _members_of_body(body)
        classes[name] = {"fields": fields, "methods": methods,
                         "inherits": inherits, "body": body}
    return classes


def _java_undeclared_members(code: str) -> tuple[bool, str]:
    """Reject references to fields/methods that a user-defined class does not declare.

    Only checks variables provably typed to a class declared in THIS snippet (and
    `this` inside such a class). Library types (HashMap, etc.) and classes that
    extend/implement another type are never checked, so false positives are avoided.
    """
    classes = _java_class_members(code)
    if not classes:
        return True, ""
    cleaned = _strip_java_noise(code)

    # Map variable name -> user class type (declarations, fields, parameters).
    var_types = {}
    for cname in classes:
        for vm in re.finditer(rf"\b{re.escape(cname)}\b\s+([A-Za-z_]\w*)", cleaned):
            var = vm.group(1)
            if var not in _JAVA_KEYWORDS:
                var_types.setdefault(var, cname)

    # 1) variable.member references.
    for am in _JAVA_MEMBER_ACCESS_RE.finditer(cleaned):
        obj, member, is_call = am.group(1), am.group(2), bool(am.group(3))
        if obj == "this" or obj not in var_types:
            continue
        info = classes[var_types[obj]]
        if info["inherits"]:
            continue
        allowed = info["fields"] | info["methods"]
        if not allowed or member in allowed:
            continue
        kind = "method" if is_call else "field"
        return False, (
            f"references '{obj}.{member}' but class '{var_types[obj]}' declares no such "
            f"{kind} (declared: {', '.join(sorted(allowed))}). Declare the '{member}' "
            f"{kind} on '{var_types[obj]}' or fix the reference."
        )

    # 2) this.member references inside each (non-inheriting) class body.
    for cname, info in classes.items():
        if info["inherits"]:
            continue
        allowed = info["fields"] | info["methods"]
        if not allowed:
            continue
        for tm in re.finditer(r"\bthis\s*\.\s*([A-Za-z_]\w*)\s*(\()?", info["body"]):
            member, is_call = tm.group(1), bool(tm.group(2))
            if member in allowed:
                continue
            kind = "method" if is_call else "field"
            return False, (
                f"references 'this.{member}' but class '{cname}' declares no such "
                f"{kind} (declared: {', '.join(sorted(allowed))}). Declare the '{member}' "
                f"{kind} on '{cname}' or fix the reference."
            )

    return True, ""


_JAVA_NEW_RE = re.compile(r"\bnew\s+([A-Z][A-Za-z0-9_]*)\s*(?:<[^;{}]*>)?\s*\(")
_JAVA_WILDCARD_IMPORT_RE = re.compile(r"\bimport\s+(?:static\s+)?[\w.]+\.\*\s*;")
_JAVA_IMPORT_RE = re.compile(r"\bimport\s+(?:static\s+)?([\w.]+)\s*;")


def _java_undefined_classes(code: str) -> tuple[bool, str]:
    """Reject instantiation (`new Foo(...)`) of a class that is neither declared in
    the snippet, imported, nor a known JDK type.

    Conservative: if ANY wildcard import (`import x.y.*;`) is present we cannot
    resolve names, so the check is skipped entirely.
    """
    cleaned = _strip_java_noise(code)
    if _JAVA_WILDCARD_IMPORT_RE.search(cleaned):
        return True, ""

    declared = set(_java_class_members(code))
    imported = set()
    for m in _JAVA_IMPORT_RE.finditer(cleaned):
        imported.add(m.group(1).split(".")[-1])

    known = (declared | imported | _JAVA_LANG_TYPES | _JAVA_IMPORT_TYPES | _JDK_COMMON)
    for m in _JAVA_NEW_RE.finditer(cleaned):
        name = m.group(1)
        if len(name) == 1:  # single-letter generic type parameter
            continue
        if name in known:
            continue
        return False, (
            f"uses undefined class '{name}' (`new {name}(...)`) that is not declared "
            "in the code, imported, or a standard JDK type. Define the class or add "
            "the correct import."
        )
    return True, ""


def check_java(code: str) -> tuple[bool, str]:
    public_classes = _java_public_classes(code)
    if len(public_classes) > 1:
        return False, (
            "Java allows only one public top-level class per file. "
            f"Found: {', '.join(public_classes)}."
        )

    ok, reason = _java_balanced_braces(code)
    if not ok:
        return False, reason

    ok, reason = _java_invalid_declarations(code)
    if not ok:
        return False, reason

    ok, reason = _java_method_returns(code)
    if not ok:
        return False, reason

    ok, reason = _java_imports(code)
    if not ok:
        return False, reason

    ok, reason = _java_undefined_classes(code)
    if not ok:
        return False, reason

    ok, reason = _java_undeclared_members(code)
    if not ok:
        return False, reason

    return True, ""


# ---------------------------------------------------------------------------
# C++
# ---------------------------------------------------------------------------
def _cpp_multiple_main(code: str) -> tuple[bool, str]:
    count = len(re.findall(r"\bint\s+main\s*\(", code))
    if count > 1:
        return False, f"C++ code contains {count} main functions; only one is allowed."
    return True, ""


def _cpp_balanced_braces(code: str) -> tuple[bool, str]:
    cleaned = re.sub(r"//.*?$", "", code, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'"(?:\\"|[^"])*"', '""', cleaned)
    for open_c, close_c in [("{", "}"), ("(", ")"), ("[", "]")]:
        if cleaned.count(open_c) != cleaned.count(close_c):
            return False, f"Unbalanced '{open_c}{close_c}' in C++ code."
    return True, ""


def _cpp_headers(code: str) -> tuple[bool, str]:
    headers = re.findall(r"#include\s*[\"<]([^\"<>\s]+)[\"\>]", code)
    headers = [h.lower() for h in headers]
    missing = set()
    for symbol, header in _CPP_HEADER_NEEDS.items():
        if re.search(rf"\b{re.escape(symbol)}\b", code) and header not in headers:
            missing.add(header)
    if missing:
        return False, (
            "C++ code appears to use symbols that require the following headers: "
            f"{', '.join(sorted(missing))}. Add `#include <...>` for them."
        )
    return True, ""


_CPP_CLASS_HEADER_RE = re.compile(
    r"\b(?:struct|class)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(:[^{;]*)?\{"
)
_CPP_METHOD_RE = re.compile(
    r"([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\b\s*)?(?:noexcept\b\s*)?"
    r"(?:override\b\s*)?(?:final\b\s*)?(?:->[^{};]*)?(?::[^{}]*)?$"
)
_CPP_FIELD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|const|mutable|virtual|inline|"
    r"constexpr|volatile)\s+)*"
    r"[A-Za-z_][\w:]*(?:\s*<[^>]*>)?[\s*&]+"
    r"(\**\s*[A-Za-z_][\w,*&\s\[\]]*?)\s*(?:=[^;]*|\{[^}]*\})?$",
    re.DOTALL,
)
_CPP_MEMBER_ACCESS_RE = re.compile(
    r"(?<![.\w>])([A-Za-z_]\w*)\s*(?:\.|->)\s*([A-Za-z_]\w*)\s*(\()?"
)
_CPP_DECL_SKIP_RE = re.compile(
    r"^(?:public|private|protected|using|typedef|friend|template|return|"
    r"namespace|else|do|try)\b"
)


def _cpp_field_names(seg: str, fields: set) -> None:
    seg = seg.strip()
    if not seg or _CPP_DECL_SKIP_RE.match(seg):
        return
    m = _CPP_FIELD_RE.match(seg)
    if not m:
        return
    for raw in m.group(1).split(","):
        nm = raw.strip().lstrip("*& ").strip()
        nm = re.sub(r"\s*\[.*\]$", "", nm)
        nm = re.sub(r"\s*[={].*$", "", nm).strip()
        if re.fullmatch(r"[A-Za-z_]\w*", nm):
            fields.add(nm)


def _cpp_members_of_body(body: str) -> tuple[set, set]:
    fields, methods = set(), set()
    depth = 0
    buf = []
    for c in body:
        if c == "{":
            if depth == 0:
                seg = "".join(buf)
                mm = _CPP_METHOD_RE.search(seg)
                if mm:
                    methods.add(mm.group(1))
                else:
                    _cpp_field_names(seg, fields)
            depth += 1
            buf = []
        elif c == "}":
            depth = max(0, depth - 1)
            buf = []
        elif c == ";":
            if depth == 0:
                seg = "".join(buf)
                mm = _CPP_METHOD_RE.search(seg)
                if mm:
                    methods.add(mm.group(1))  # method prototype
                else:
                    _cpp_field_names(seg, fields)
            buf = []
        elif c == ":" and depth == 0 and "".join(buf).strip() in (
                "public", "private", "protected"):
            buf = []  # access specifier
        elif depth == 0:
            buf.append(c)
    return fields, methods


def _cpp_class_members(code: str) -> dict:
    cleaned = _strip_java_noise(code)
    classes = {}
    for m in _CPP_CLASS_HEADER_RE.finditer(cleaned):
        name = m.group(1)
        inherits = bool(m.group(2))
        open_idx = m.end() - 1
        depth, i, n = 0, open_idx, len(cleaned)
        while i < n:
            ch = cleaned[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = cleaned[open_idx + 1:i]
        fields, methods = _cpp_members_of_body(body)
        classes[name] = {"fields": fields, "methods": methods,
                         "inherits": inherits, "body": body}
    return classes


def _cpp_undeclared_members(code: str) -> tuple[bool, str]:
    """Reject `obj.member` / `obj->member` / `this->member` where the user struct/
    class declares no such member. Library types and inheriting classes are skipped."""
    classes = _cpp_class_members(code)
    if not classes:
        return True, ""
    cleaned = _strip_java_noise(code)

    var_types = {}
    for cname in classes:
        for vm in re.finditer(rf"\b{re.escape(cname)}\b\s*[*&]?\s*([A-Za-z_]\w*)", cleaned):
            var = vm.group(1)
            if var not in _JAVA_KEYWORDS and var not in ("const", "struct", "class"):
                var_types.setdefault(var, cname)

    for am in _CPP_MEMBER_ACCESS_RE.finditer(cleaned):
        obj, member, is_call = am.group(1), am.group(2), bool(am.group(3))
        if obj == "this" or obj not in var_types:
            continue
        info = classes[var_types[obj]]
        if info["inherits"]:
            continue
        allowed = info["fields"] | info["methods"]
        if not allowed or member in allowed:
            continue
        kind = "method" if is_call else "field"
        return False, (
            f"references '{obj}.{member}'/'{obj}->{member}' but type '{var_types[obj]}' "
            f"declares no such {kind} (declared: {', '.join(sorted(allowed))}). Declare "
            f"the '{member}' {kind} or fix the reference."
        )

    for cname, info in classes.items():
        if info["inherits"]:
            continue
        allowed = info["fields"] | info["methods"]
        if not allowed:
            continue
        for tm in re.finditer(r"\bthis\s*->\s*([A-Za-z_]\w*)\s*(\()?", info["body"]):
            member, is_call = tm.group(1), bool(tm.group(2))
            if member in allowed:
                continue
            kind = "method" if is_call else "field"
            return False, (
                f"references 'this->{member}' but type '{cname}' declares no such "
                f"{kind} (declared: {', '.join(sorted(allowed))}). Declare the "
                f"'{member}' {kind} or fix the reference."
            )

    return True, ""


def check_cpp(code: str) -> tuple[bool, str]:
    ok, reason = _cpp_multiple_main(code)
    if not ok:
        return False, reason
    ok, reason = _cpp_balanced_braces(code)
    if not ok:
        return False, reason
    ok, reason = _cpp_headers(code)
    if not ok:
        return False, reason
    ok, reason = _cpp_undeclared_members(code)
    if not ok:
        return False, reason
    return True, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _normalize_lang(lang: str) -> str:
    lang = (lang or "").strip().lower()
    if lang in ("py", "python3"):
        return "python"
    if lang in ("cpp", "c++", "cxx", "cc"):
        return "cpp"
    if lang in ("java", "js"):
        return "java"
    if lang in ("c", "csharp", "cs", "go", "javascript", "typescript"):
        return "unsupported"  # We don't gate-check these languages.
    return "python"  # Default to python if no language tag.


def check_code(lang: str, code: str) -> tuple[bool, str]:
    """Run compile checks for a single code block."""
    norm = _normalize_lang(lang)
    if norm == "python":
        return check_python(code)
    if norm == "java":
        return check_java(code)
    if norm == "cpp":
        return check_cpp(code)
    return True, ""


def check(user_query: str, response_text: str) -> tuple[bool, str]:
    """Deterministic compile verifier for DSA/code generation answers.

    Returns (ok, reason). If the response contains no code block, or the query
    is conceptual, it returns (True, "") so the LLM critic handles the rest.
    """
    text = response_text or ""
    # Conceptual/no-code answers are not gate-checked.
    if not any(b for _, b in extract_code_blocks(text)):
        return True, ""

    for lang, code in extract_code_blocks(text):
        if not code.strip():
            continue
        ok, reason = check_code(lang, code)
        if not ok:
            logger.warning(f"[COMPILE_VERIFIER] {lang}: {reason}")
            return False, f"Compile/syntax error: {reason}"
    return True, ""


def critique(user_query: str, response_text: str) -> dict:
    """Convenience wrapper matching the critic interface."""
    ok, reason = check(user_query, response_text)
    return {"verified": ok, "feedback": reason}
