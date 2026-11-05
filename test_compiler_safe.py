# -*- coding: utf-8 -*-
"""
Tests for the Compiler-Safe Code Engine (code_sanitizer.py).
Verifies auto-fix for Java, C++, C, Python, SQL, and JavaScript.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import os
sys.path.insert(0, os.path.dirname(__file__))

from code_sanitizer import validate_code_block, sanitize_fenced_code, postprocess_codeme_response, strip_markup_artifacts

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -- {detail}")


print("\n===============================================")
print("  COMPILER-SAFE ENGINE TESTS")
print("===============================================\n")

# ─────────────────────────────────────────────
# 1. JAVA — auto-add missing imports
# ─────────────────────────────────────────────
print("-- JAVA TESTS --")

java_missing_import = """public class Main {
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        ArrayList<Integer> list = new ArrayList<>();
        list.add(10);
        System.out.println(list);
    }
}"""

fixed, warns = validate_code_block(java_missing_import, "java")
check("Java: auto-adds Scanner import", "import java.util.Scanner;" in fixed, fixed[:200])
check("Java: auto-adds ArrayList import", "import java.util.ArrayList;" in fixed, fixed[:200])

java_complete = """import java.util.Scanner;
public class Main {
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        System.out.println("Hello");
    }
}"""
fixed2, warns2 = validate_code_block(java_complete, "java")
check("Java: doesn't duplicate existing imports", fixed2.count("import java.util.Scanner;") == 1)

java_missing_brace = """public class Main {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
"""
fixed3, _ = validate_code_block(java_missing_brace, "java")
check("Java: auto-fixes missing closing brace", fixed3.rstrip().endswith("}"), f"ends with: '{fixed3[-20:]}'")

# ─────────────────────────────────────────────
# 2. C++ — auto-add missing headers + namespace
# ─────────────────────────────────────────────
print("\n-- C++ TESTS --")

cpp_no_headers = """int main() {
    cout << "Hello World" << endl;
    vector<int> v = {1, 2, 3};
    sort(v.begin(), v.end());
    return 0;
}"""

fixed, warns = validate_code_block(cpp_no_headers, "cpp")
check("C++: auto-adds <iostream>", "#include <iostream>" in fixed, fixed[:300])
check("C++: auto-adds <vector>", "#include <vector>" in fixed, fixed[:300])
check("C++: auto-adds <algorithm>", "#include <algorithm>" in fixed, fixed[:300])
check("C++: auto-adds 'using namespace std;'", "using namespace std;" in fixed, fixed[:300])

cpp_no_return = """#include <iostream>
using namespace std;
int main() {
    cout << "Hello";
}"""

fixed2, _ = validate_code_block(cpp_no_return, "cpp")
check("C++: auto-adds 'return 0;'", "return 0;" in fixed2, fixed2)

cpp_complete = """#include <iostream>
using namespace std;
int main() {
    cout << "Already complete" << endl;
    return 0;
}"""
fixed3, warns3 = validate_code_block(cpp_complete, "cpp")
check("C++: doesn't modify already-complete code", fixed3.count("#include <iostream>") == 1)

# ─────────────────────────────────────────────
# 3. C — auto-add missing headers
# ─────────────────────────────────────────────
print("\n-- C TESTS --")

c_no_headers = """int main() {
    printf("Hello %d\\n", 42);
    int *p = (int *)malloc(sizeof(int) * 10);
    free(p);
    return 0;
}"""

fixed, warns = validate_code_block(c_no_headers, "c")
check("C: auto-adds <stdio.h>", "#include <stdio.h>" in fixed, fixed[:200])
check("C: auto-adds <stdlib.h>", "#include <stdlib.h>" in fixed, fixed[:200])

c_no_return = """#include <stdio.h>
int main() {
    printf("Hello");
}"""

fixed2, _ = validate_code_block(c_no_return, "c")
check("C: auto-adds 'return 0;'", "return 0;" in fixed2, fixed2)

# ─────────────────────────────────────────────
# 4. PYTHON — syntax validation
# ─────────────────────────────────────────────
print("\n-- PYTHON TESTS --")

py_valid = """def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        print(a, end=' ')
        a, b = b, a + b

fibonacci(10)"""

fixed, warns = validate_code_block(py_valid, "python")
check("Python: valid code passes", len(warns) == 0 or all("unbalanced" not in w for w in warns))

py_missing_colon = """def hello()
    print("world")"""

fixed2, warns2 = validate_code_block(py_missing_colon, "python")
check("Python: detects/attempts fix for missing colon", ":" in fixed2.split("\n")[0], fixed2)

# ─────────────────────────────────────────────
# 5. SQL — trailing semicolons
# ─────────────────────────────────────────────
print("\n-- SQL TESTS --")

sql_no_semi = "SELECT * FROM employees WHERE salary > 50000"
fixed, _ = validate_code_block(sql_no_semi, "sql")
check("SQL: auto-adds trailing semicolon", fixed.strip().endswith(";"), fixed)

sql_with_semi = "SELECT * FROM employees WHERE salary > 50000;"
fixed2, _ = validate_code_block(sql_with_semi, "sql")
check("SQL: doesn't duplicate semicolon", fixed2.count(";") == 1, fixed2)

# ─────────────────────────────────────────────
# 6. JAVASCRIPT — brace fix
# ─────────────────────────────────────────────
print("\n-- JAVASCRIPT TESTS --")

js_missing_brace = """function hello() {
    console.log("Hello");
    if (true) {
        console.log("World");
    }
"""
fixed, _ = validate_code_block(js_missing_brace, "javascript")
check("JS: auto-fixes missing closing brace", fixed.count("{") == fixed.count("}"), f"{{ = {fixed.count('{')}, }} = {fixed.count('}')}")

# ─────────────────────────────────────────────
# 7. MARKUP STRIPPING
# ─────────────────────────────────────────────
print("\n-- MARKUP STRIPPING TESTS --")

polluted = '<span class="hljs-keyword">int</span> main() { <span class="hljs-built_in">cout</span> &lt;&lt; "hello"; }'
clean = strip_markup_artifacts(polluted)
check("Strips hljs spans", "<span" not in clean, clean)
check("Decodes &lt; entities", "<<" in clean, clean)

# ─────────────────────────────────────────────
# 8. FULL PIPELINE (postprocess_codeme_response)
# ─────────────────────────────────────────────
print("\n-- FULL PIPELINE TEST --")

full_response = """Here's the C++ code for finding the third largest number:

```cpp
int main() {
    int arr[] = {10, 20, 30, 40, 50};
    int n = 5;
    sort(arr, arr + n);
    cout << "Third largest: " << arr[n - 3] << endl;
}
```

This sorts the array and picks the third element from the end."""

processed = postprocess_codeme_response(full_response)
check("Pipeline: adds missing <iostream>", "#include <iostream>" in processed, processed[:300])
check("Pipeline: adds missing <algorithm>", "#include <algorithm>" in processed, processed[:300])
check("Pipeline: adds 'using namespace std;'", "using namespace std;" in processed, processed[:300])
check("Pipeline: adds 'return 0;'", "return 0;" in processed, processed[:400])

# ─────────────────────────────────────────────
# 9. LANGUAGE ALIAS NORMALIZATION
# ─────────────────────────────────────────────
print("\n-- LANG ALIAS TESTS --")

from code_sanitizer import _normalize_lang
check("'py' → 'python'", _normalize_lang("py") == "python")
check("'js' → 'javascript'", _normalize_lang("js") == "javascript")
check("'c++' → 'cpp'", _normalize_lang("c++") == "cpp")
check("'node' → 'javascript'", _normalize_lang("node") == "javascript")
check("'react' → 'jsx'", _normalize_lang("react") == "jsx")

# ─────────────────────────────────────────────
print(f"\n===============================================")
print(f"  RESULTS: {PASS} passed, {FAIL} failed")
print(f"===============================================\n")

if FAIL > 0:
    sys.exit(1)
