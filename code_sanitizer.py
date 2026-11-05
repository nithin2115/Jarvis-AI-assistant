"""
Code-Me Compiler-Safe Engine — validates, auto-fixes, and sanitizes AI code output.
Ensures every code block is immediately runnable when copy-pasted into
Programiz, Replit, VS Code, IntelliJ, or any online/local compiler.

Pipeline:
  1. Strip HTML/highlight.js/render artifacts
  2. Language-aware structural validation
  3. Auto-fix missing imports, headers, entry points, braces
  4. Verify syntax where possible (Python compile check)
"""
import re
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger("jarvis.code")

# ── Patterns that must never appear inside code fences ─────────────────────────
# Only match actual HTML tags (not C++ templates like vector<int>, map<string,int>)
_HTML_TAGS = r"(?:span|div|p|br|a|code|pre|em|strong|b|i|u|ul|ol|li|table|tr|td|th|h[1-6]|img|hr|section|article|nav|header|footer|main|aside|details|summary|mark|small|sub|sup|del|ins|blockquote|figure|figcaption|abbr|cite|dfn|kbd|samp|var|wbr|ruby|rt|rp|bdi|bdo|data|time|meter|progress|output|canvas|svg|path|g|rect|circle|line|polyline|polygon|text|tspan|use|defs|symbol|desc|title|style|script|link|meta|head|body|html|form|input|button|select|option|textarea|label|fieldset|legend|datalist|optgroup|noscript|template|slot|iframe|embed|object|param|source|track|audio|video|picture|map|area)"
_HTML_TAG_RE = re.compile(r"</?(?:" + _HTML_TAGS + r")(?:\s[^>]*)?>", re.I)
_HLJS_SPAN_RE = re.compile(r"</?span[^>]*>", re.I)
_HLJS_CLASS_RE = re.compile(r'\bclass\s*=\s*["\']hljs-[^"\']*["\']', re.I)
_ENTITY_RE = re.compile(r"&(?:lt|gt|amp|quot|#39|#x[0-9a-f]+);", re.I)

_FENCE_RE = re.compile(r"```(\w*)\n?([\s\S]*?)```", re.MULTILINE)

_LANG_ALIASES = {
    "js": "javascript", "ts": "typescript", "py": "python",
    "cpp": "cpp", "c++": "cpp", "c": "c", "java": "java",
    "sql": "sql", "bash": "bash", "sh": "shell", "shell": "bash",
    "jsx": "jsx", "tsx": "tsx", "react": "jsx",
    "node": "javascript", "nodejs": "javascript",
}


def _decode_entities(text: str) -> str:
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )


def strip_markup_artifacts(code: str) -> str:
    """Remove HTML/syntax-highlight pollution from a code string."""
    if not code:
        return code
    original = code
    code = _HLJS_SPAN_RE.sub("", code)
    code = _HTML_TAG_RE.sub("", code)
    code = _HLJS_CLASS_RE.sub("", code)
    code = _decode_entities(code)
    # Stray attribute fragments from broken copies
    code = re.sub(r'\bhljs-[a-z0-9_-]+\b', "", code, flags=re.I)
    code = re.sub(r'["\']?\s*hljs-[a-z]+["\']?', "", code, flags=re.I)
    code = re.sub(r"\n{3,}", "\n\n", code)
    if code != original:
        logger.info("[SANITIZE] stripped markup artifacts from code block")
    return code.rstrip() + ("\n" if original.endswith("\n") else "")


def _normalize_lang(lang: str) -> str:
    lang = (lang or "").strip().lower()
    return _LANG_ALIASES.get(lang, lang or "text")


# ══════════════════════════════════════════════════════════════════════════════
#  STRUCTURAL CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def _balance_check(code: str) -> List[str]:
    """Return list of structural warnings (non-fatal)."""
    warnings = []
    pairs = [("{", "}"), ("(", ")"), ("[", "]")]
    for open_c, close_c in pairs:
        diff = code.count(open_c) - code.count(close_c)
        if diff != 0:
            warnings.append(f"unbalanced '{open_c}{close_c}' (diff={diff})")
    return warnings


def _auto_fix_braces(code: str, lang: str) -> str:
    """Auto-fix simple brace imbalance (off by 1-2 closing braces)."""
    if lang not in ("java", "cpp", "c", "javascript", "typescript", "jsx", "tsx"):
        return code

    open_count = code.count("{")
    close_count = code.count("}")
    diff = open_count - close_count

    if diff > 0 and diff <= 2:
        # Missing closing braces — append them
        code = code.rstrip()
        for _ in range(diff):
            code += "\n}"
        logger.info(f"[AUTOFIX] appended {diff} missing closing brace(s) [{lang}]")
    return code


# ══════════════════════════════════════════════════════════════════════════════
#  JAVA AUTO-FIX
# ══════════════════════════════════════════════════════════════════════════════

# Common Java imports and the types that require them
_JAVA_IMPORT_MAP = {
    "Scanner":       "import java.util.Scanner;",
    "ArrayList":     "import java.util.ArrayList;",
    "LinkedList":    "import java.util.LinkedList;",
    "HashMap":       "import java.util.HashMap;",
    "HashSet":       "import java.util.HashSet;",
    "TreeMap":       "import java.util.TreeMap;",
    "TreeSet":       "import java.util.TreeSet;",
    "Map":           "import java.util.Map;",
    "List":          "import java.util.List;",
    "Set":           "import java.util.Set;",
    "Queue":         "import java.util.Queue;",
    "Stack":         "import java.util.Stack;",
    "PriorityQueue": "import java.util.PriorityQueue;",
    "Collections":   "import java.util.Collections;",
    "Arrays":        "import java.util.Arrays;",
    "Iterator":      "import java.util.Iterator;",
    "LinkedHashMap": "import java.util.LinkedHashMap;",
    "Deque":         "import java.util.Deque;",
    "ArrayDeque":    "import java.util.ArrayDeque;",
    "Comparator":    "import java.util.Comparator;",
    "Random":        "import java.util.Random;",
    "BufferedReader": "import java.io.BufferedReader;",
    "InputStreamReader": "import java.io.InputStreamReader;",
    "IOException":   "import java.io.IOException;",
    "File":          "import java.io.File;",
    "FileReader":    "import java.io.FileReader;",
    "FileWriter":    "import java.io.FileWriter;",
    "PrintWriter":   "import java.io.PrintWriter;",
    "Stream":        "import java.util.stream.Stream;",
    "Collectors":    "import java.util.stream.Collectors;",
    "Math":          "",  # java.lang — no import needed
}


def _validate_java(code: str, warnings: List[str]) -> str:
    """Validate and auto-fix Java code for compiler safety."""
    # Strip markup first
    if 'class="hljs' in code or "<span" in code:
        code = strip_markup_artifacts(code)

    lines = code.split("\n")

    # 1. Auto-detect and add missing imports
    existing_imports = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import "):
            existing_imports.add(stripped)

    needed_imports = []
    for type_name, import_stmt in _JAVA_IMPORT_MAP.items():
        if not import_stmt:
            continue  # java.lang types don't need import
        # Check if the type is used in the code (word boundary match)
        if re.search(r'\b' + type_name + r'\b', code):
            if import_stmt not in existing_imports:
                needed_imports.append(import_stmt)

    if needed_imports:
        # Find the insertion point — after existing imports or at the top
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("package "):
                insert_idx = i + 1
        for imp in sorted(set(needed_imports)):
            lines.insert(insert_idx, imp)
            insert_idx += 1
        logger.info(f"[AUTOFIX] Java: added {len(needed_imports)} missing imports")

    code = "\n".join(lines)

    # 2. Check for main method
    has_class = bool(re.search(r'\bclass\s+\w+', code))
    has_main = bool(re.search(r'(public\s+)?static\s+(void\s+)?main\s*\(', code) or
                    re.search(r'void\s+main\s*\(\s*String', code))

    if has_class and not has_main:
        warnings.append("java: no main method — may not run standalone")

    # 3. Fix braces
    code = _auto_fix_braces(code, "java")

    return code


# ══════════════════════════════════════════════════════════════════════════════
#  C++ AUTO-FIX
# ══════════════════════════════════════════════════════════════════════════════

_CPP_HEADER_MAP = {
    "cout":           "#include <iostream>",
    "cin":            "#include <iostream>",
    "cerr":           "#include <iostream>",
    "endl":           "#include <iostream>",
    "vector":         "#include <vector>",
    "map":            "#include <map>",
    "unordered_map":  "#include <unordered_map>",
    "set":            "#include <set>",
    "unordered_set":  "#include <unordered_set>",
    "stack":          "#include <stack>",
    "queue":          "#include <queue>",
    "priority_queue": "#include <queue>",
    "deque":          "#include <deque>",
    "list":           "#include <list>",
    "pair":           "#include <utility>",
    "make_pair":      "#include <utility>",
    "sort":           "#include <algorithm>",
    "reverse":        "#include <algorithm>",
    "min_element":    "#include <algorithm>",
    "max_element":    "#include <algorithm>",
    "find":           "#include <algorithm>",
    "count":          "#include <algorithm>",
    "lower_bound":    "#include <algorithm>",
    "upper_bound":    "#include <algorithm>",
    "binary_search":  "#include <algorithm>",
    "next_permutation": "#include <algorithm>",
    "string":         "#include <string>",
    "to_string":      "#include <string>",
    "stoi":           "#include <string>",
    "getline":        "#include <string>",
    "sqrt":           "#include <cmath>",
    "pow":            "#include <cmath>",
    "abs":            "#include <cstdlib>",
    "malloc":         "#include <cstdlib>",
    "free":           "#include <cstdlib>",
    "srand":          "#include <cstdlib>",
    "rand":           "#include <cstdlib>",
    "strlen":         "#include <cstring>",
    "strcpy":         "#include <cstring>",
    "memset":         "#include <cstring>",
    "setw":           "#include <iomanip>",
    "setprecision":   "#include <iomanip>",
    "fixed":          "#include <iomanip>",
    "fstream":        "#include <fstream>",
    "ifstream":       "#include <fstream>",
    "ofstream":       "#include <fstream>",
    "stringstream":   "#include <sstream>",
    "INT_MAX":        "#include <climits>",
    "INT_MIN":        "#include <climits>",
    "LLONG_MAX":      "#include <climits>",
    "numeric_limits":  "#include <limits>",
    "bitset":         "#include <bitset>",
    "tuple":          "#include <tuple>",
    "make_tuple":     "#include <tuple>",
    "array":          "#include <array>",
    "assert":         "#include <cassert>",
}


def _cpp_syntax_integrity_check(code: str) -> str:
    """
    Detect and repair C++ syntax corruption patterns.
    Catches issues caused by HTML/rendering pipeline mangling:
      - Truncated #include (missing <header>)
      - Malformed stream operators (cout > x instead of cin >> x)
      - Broken for-loops (missing condition/increment)
      - Incomplete expressions
    """
    lines = code.split("\n")
    fixed_lines = []
    fixes_applied = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        fixed = line

        # ── Fix 1: Truncated #include — missing <header> ──
        # e.g. "#include " (trailing space, nothing after) or "#include" alone on a line
        if re.match(r'^#include\s*$', stripped):
            # Bare #include with nothing — add <iostream> as default
            fixed = "#include <iostream>"
            fixes_applied += 1
            logger.info(f"[INTEGRITY] Line {i+1}: Fixed bare '#include' → '#include <iostream>'")

        # ── Fix 2: #include with broken/empty angle brackets ──
        elif re.match(r'^#include\s+<\s*>$', stripped):
            fixed = "#include <iostream>"
            fixes_applied += 1
            logger.info(f"[INTEGRITY] Line {i+1}: Fixed '#include <>' → '#include <iostream>'")

        # ── Fix 3: Malformed stream operators ──
        # "cout > x" should be "cin >> x" (common corruption pattern)
        # Only fix when it's clearly a stream operation context
        elif re.match(r'^\s*(std::)?cout\s+>', stripped) and '>>' not in stripped and '<<' not in stripped:
            # cout > something → likely meant cout << something
            fixed = re.sub(r'\bcout\s+>', 'cout <<', fixed)
            fixes_applied += 1
            logger.info(f"[INTEGRITY] Line {i+1}: Fixed 'cout >' → 'cout <<'")
        elif re.match(r'^\s*(std::)?cin\s+<', stripped) and '<<' not in stripped and '>>' not in stripped:
            # cin < something → likely meant cin >> something
            fixed = re.sub(r'\bcin\s+<', 'cin >>', fixed)
            fixes_applied += 1
            logger.info(f"[INTEGRITY] Line {i+1}: Fixed 'cin <' → 'cin >>'")

        # ── Fix 4: Single > or < for stream operators ──
        # "cout > variable;" (single > after cout, should be <<)
        if re.search(r'\bcout\s*>\s*\w', fixed) and '>>' not in fixed and '<<' not in fixed:
            fixed = re.sub(r'\bcout(\s*)>(\s*)', r'cout\1<<\2', fixed)
            fixes_applied += 1
        if re.search(r'\bcin\s*<\s*\w', fixed) and '>>' not in fixed and '<<' not in fixed:
            fixed = re.sub(r'\bcin(\s*)<(\s*)', r'cin\1>>\2', fixed)
            fixes_applied += 1

        fixed_lines.append(fixed)

    if fixes_applied:
        logger.info(f"[INTEGRITY] C++ syntax integrity: {fixes_applied} fix(es) applied")

    return "\n".join(fixed_lines)


def _validate_cpp(code: str, warnings: List[str]) -> str:
    """Validate and auto-fix C++ code for compiler safety."""

    # ── Pre-pass: syntax integrity check (catches rendering corruption) ──
    code = _cpp_syntax_integrity_check(code)

    lines = code.split("\n")

    # 1. Collect existing includes
    existing_includes = set()
    for line in lines:
        stripped = line.strip()
        m = re.match(r'#include\s*[<"]([^>"]+)[>"]', stripped)
        if m:
            existing_includes.add(stripped)

    # 2. Auto-detect needed headers
    needed_headers = set()
    for keyword, header in _CPP_HEADER_MAP.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', code):
            if header and header not in existing_includes:
                needed_headers.add(header)

    # 3. Check for 'using namespace std;'
    has_using_ns = bool(re.search(r'using\s+namespace\s+std\s*;', code))
    uses_std = bool(re.search(r'\b(cout|cin|cerr|endl|string|vector|map|set|sort|getline|stoi|to_string)\b', code))

    # 4. Check for int main()
    has_main = bool(re.search(r'\bint\s+main\s*\(', code))

    # 5. Check for return 0
    has_return = bool(re.search(r'\breturn\s+0\s*;', code))

    # Build the fixed code
    prepend_lines = []

    if needed_headers:
        for h in sorted(needed_headers):
            prepend_lines.append(h)
        logger.info(f"[AUTOFIX] C++: added {len(needed_headers)} missing headers")

    # Find where to insert — after existing includes
    if prepend_lines:
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#include") or stripped.startswith("#pragma") or stripped.startswith("#define"):
                insert_idx = i + 1
        for h in prepend_lines:
            lines.insert(insert_idx, h)
            insert_idx += 1

    # Add 'using namespace std;' if needed
    if uses_std and not has_using_ns:
        # Insert after last #include
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("#include") or line.strip().startswith("#pragma"):
                insert_idx = i + 1
        lines.insert(insert_idx, "using namespace std;")
        lines.insert(insert_idx + 1, "")
        logger.info("[AUTOFIX] C++: added 'using namespace std;'")

    code = "\n".join(lines)

    # Add 'return 0;' before last closing brace if missing
    if has_main and not has_return:
        # Find the last } and insert return 0; before it
        rindex = code.rfind("}")
        if rindex > 0:
            code = code[:rindex] + "    return 0;\n" + code[rindex:]
            logger.info("[AUTOFIX] C++: added 'return 0;'")

    # Fix braces
    code = _auto_fix_braces(code, "cpp")

    return code


# ══════════════════════════════════════════════════════════════════════════════
#  C AUTO-FIX
# ══════════════════════════════════════════════════════════════════════════════

_C_HEADER_MAP = {
    "printf":   "#include <stdio.h>",
    "scanf":    "#include <stdio.h>",
    "puts":     "#include <stdio.h>",
    "gets":     "#include <stdio.h>",
    "fprintf":  "#include <stdio.h>",
    "fscanf":   "#include <stdio.h>",
    "fopen":    "#include <stdio.h>",
    "fclose":   "#include <stdio.h>",
    "fgets":    "#include <stdio.h>",
    "sprintf":  "#include <stdio.h>",
    "sscanf":   "#include <stdio.h>",
    "malloc":   "#include <stdlib.h>",
    "calloc":   "#include <stdlib.h>",
    "realloc":  "#include <stdlib.h>",
    "free":     "#include <stdlib.h>",
    "exit":     "#include <stdlib.h>",
    "atoi":     "#include <stdlib.h>",
    "atof":     "#include <stdlib.h>",
    "rand":     "#include <stdlib.h>",
    "srand":    "#include <stdlib.h>",
    "abs":      "#include <stdlib.h>",
    "strlen":   "#include <string.h>",
    "strcpy":   "#include <string.h>",
    "strncpy":  "#include <string.h>",
    "strcmp":    "#include <string.h>",
    "strcat":   "#include <string.h>",
    "memset":   "#include <string.h>",
    "memcpy":   "#include <string.h>",
    "sqrt":     "#include <math.h>",
    "pow":      "#include <math.h>",
    "ceil":     "#include <math.h>",
    "floor":    "#include <math.h>",
    "log":      "#include <math.h>",
    "sin":      "#include <math.h>",
    "cos":      "#include <math.h>",
    "isalpha":  "#include <ctype.h>",
    "isdigit":  "#include <ctype.h>",
    "toupper":  "#include <ctype.h>",
    "tolower":  "#include <ctype.h>",
    "time":     "#include <time.h>",
    "clock":    "#include <time.h>",
    "assert":   "#include <assert.h>",
    "bool":     "#include <stdbool.h>",
    "true":     "#include <stdbool.h>",
    "false":    "#include <stdbool.h>",
    "INT_MAX":  "#include <limits.h>",
    "INT_MIN":  "#include <limits.h>",
}


def _validate_c(code: str, warnings: List[str]) -> str:
    """Validate and auto-fix C code for compiler safety."""
    lines = code.split("\n")

    # Collect existing includes
    existing_includes = set()
    for line in lines:
        stripped = line.strip()
        m = re.match(r'#include\s*[<"]([^>"]+)[>"]', stripped)
        if m:
            existing_includes.add(stripped)

    # Auto-detect needed headers
    needed_headers = set()
    for keyword, header in _C_HEADER_MAP.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', code):
            if header not in existing_includes:
                needed_headers.add(header)

    # Insert needed headers
    if needed_headers:
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#include") or stripped.startswith("#define") or stripped.startswith("#pragma"):
                insert_idx = i + 1
        for h in sorted(needed_headers):
            lines.insert(insert_idx, h)
            insert_idx += 1
        logger.info(f"[AUTOFIX] C: added {len(needed_headers)} missing headers")

    code = "\n".join(lines)

    # Check for main
    has_main = bool(re.search(r'\bint\s+main\s*\(', code) or re.search(r'\bvoid\s+main\s*\(', code))
    if not has_main and re.search(r'\b(printf|scanf)\b', code):
        warnings.append("c: no main() function detected")

    # Check return 0
    has_return = bool(re.search(r'\breturn\s+0\s*;', code))
    if has_main and not has_return and re.search(r'\bint\s+main', code):
        rindex = code.rfind("}")
        if rindex > 0:
            code = code[:rindex] + "    return 0;\n" + code[rindex:]
            logger.info("[AUTOFIX] C: added 'return 0;'")

    # Fix braces
    code = _auto_fix_braces(code, "c")

    return code


# ══════════════════════════════════════════════════════════════════════════════
#  PYTHON VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def _validate_python(code: str, warnings: List[str]) -> str:
    """Validate Python code syntax."""
    if not code.strip() or code.strip().startswith("#"):
        return code
    try:
        compile(code, "<jarvis>", "exec")
    except SyntaxError as e:
        warnings.append(f"python syntax: {e.msg} (line {e.lineno})")
        # Attempt common auto-fixes
        code = _attempt_python_fixes(code, e)
    return code


def _attempt_python_fixes(code: str, error: SyntaxError) -> str:
    """Try to fix common Python syntax issues."""
    lines = code.split("\n")
    fixed = False

    if error.lineno and error.lineno <= len(lines):
        line_idx = error.lineno - 1
        line = lines[line_idx]

        # Missing colon at end of if/for/while/def/class/elif/else/try/except/finally
        if error.msg in ("expected ':'", "invalid syntax"):
            stripped = line.rstrip()
            if re.match(r'\s*(if|elif|else|for|while|def|class|try|except|finally|with)\b', stripped):
                if not stripped.endswith(":"):
                    lines[line_idx] = stripped + ":"
                    fixed = True
                    logger.info(f"[AUTOFIX] Python: added missing colon on line {error.lineno}")

    if fixed:
        code = "\n".join(lines)
        # Verify the fix worked
        try:
            compile(code, "<jarvis>", "exec")
        except SyntaxError:
            pass  # Fix didn't work — return as-is, warning already logged

    return code


# ══════════════════════════════════════════════════════════════════════════════
#  JAVASCRIPT / TYPESCRIPT VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def _validate_javascript(code: str, warnings: List[str]) -> str:
    """Validate JavaScript/TypeScript code structure."""
    if code.count("{") != code.count("}"):
        warnings.append("javascript: unbalanced braces")
    code = _auto_fix_braces(code, "javascript")
    return code


# ══════════════════════════════════════════════════════════════════════════════
#  SQL VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def _validate_sql(code: str, warnings: List[str]) -> str:
    """Validate SQL and auto-add trailing semicolons."""
    upper = code.upper().strip()
    if any(k in upper for k in ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")):
        # Ensure trailing semicolon
        stripped = code.rstrip()
        if stripped and not stripped.endswith(";"):
            code = stripped + ";"
            logger.info("[AUTOFIX] SQL: added trailing semicolon")
    return code


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN VALIDATION ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def validate_code_block(code: str, lang: str) -> Tuple[str, List[str]]:
    """Sanitize + language-aware validation + auto-fix per language."""
    lang = _normalize_lang(lang)
    code = strip_markup_artifacts(code)
    warnings = _balance_check(code)

    if lang == "java":
        code = _validate_java(code, warnings)
    elif lang == "python":
        code = _validate_python(code, warnings)
    elif lang in ("cpp", "c++"):
        code = _validate_cpp(code, warnings)
    elif lang == "c":
        code = _validate_c(code, warnings)
    elif lang in ("javascript", "js", "typescript", "ts", "jsx", "tsx"):
        code = _validate_javascript(code, warnings)
    elif lang == "sql":
        code = _validate_sql(code, warnings)

    if warnings:
        logger.debug(f"[VALIDATE] {lang}: {warnings}")
    return code, warnings


# ══════════════════════════════════════════════════════════════════════════════
#  RESPONSE-LEVEL SANITIZATION
# ══════════════════════════════════════════════════════════════════════════════

def sanitize_fenced_code(text: str) -> str:
    """Sanitize every ``` fenced block in a markdown response."""
    if not text or "```" not in text:
        return strip_markup_artifacts(text) if text else text

    out = []
    last = 0
    for m in _FENCE_RE.finditer(text):
        out.append(text[last:m.start()])
        lang = _normalize_lang(m.group(1))
        body = m.group(2)
        if body.endswith("\n"):
            body = body[:-1]
        clean, _ = validate_code_block(body, lang)
        out.append(f"```{m.group(1) or lang}\n{clean}```")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def sanitize_user_code_input(text: str) -> str:
    """Clean pasted code in user messages before sending to LLM context."""
    if not text:
        return text
    if "<span" in text or "hljs-" in text or 'class="hljs' in text:
        logger.info("[SANITIZE] cleaning user input markup artifacts")
        return sanitize_fenced_code(text) if "```" in text else strip_markup_artifacts(text)
    return text


def postprocess_codeme_response(text: str) -> str:
    """Full Code-Me post-processing pipeline — sanitize + validate + auto-fix."""
    text = sanitize_fenced_code(text)
    # Strip accidental HTML outside fences in code-heavy replies
    if 'class="hljs' in text and "```" not in text:
        text = strip_markup_artifacts(text)
    return text
