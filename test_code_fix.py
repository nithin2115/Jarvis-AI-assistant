"""
Test: Verify C++ code corruption is FIXED.
Tests both backend (code_sanitizer) and frontend (JS regex simulation).
"""
import re
import sys

# ══════════════════════════════════════════════════════════════
#  Test 1: Backend — code_sanitizer integrity check + validation
# ══════════════════════════════════════════════════════════════

from code_sanitizer import (
    validate_code_block,
    strip_markup_artifacts,
    sanitize_fenced_code,
    postprocess_codeme_response,
)

PASS = 0
FAIL = 0

def check(name, code, must_contain, lang="cpp"):
    global PASS, FAIL
    result, warnings = validate_code_block(code, lang)
    ok = True
    for expected in must_contain:
        if expected not in result:
            print(f"  ✗ FAIL: {name}")
            print(f"    Missing: {repr(expected)}")
            print(f"    Got:     {result[:200]}")
            ok = False
            FAIL += 1
            break
    if ok:
        print(f"  ✓ PASS: {name}")
        PASS += 1
    return result


print("=" * 60)
print(" BACKEND: code_sanitizer C++ validation")
print("=" * 60)

# Test: Complete C++ program passes through intact
check("Complete C++ program preserved", """
#include <iostream>
using namespace std;
int main() {
    int n;
    cin >> n;
    for (int i = 0; i < n; i++) {
        cout << i << endl;
    }
    return 0;
}
""".strip(), [
    "#include <iostream>",
    "cin >> n",
    "i < n",
    "cout << i << endl",
    "return 0;",
])

# Test: Missing include gets added
check("Auto-add missing #include", """
using namespace std;
int main() {
    cout << "Hello" << endl;
    return 0;
}
""".strip(), [
    "#include <iostream>",
    'cout << "Hello"',
])

# Test: Bare #include gets fixed
check("Fix bare #include", """
#include
using namespace std;
int main() {
    cout << "test";
    return 0;
}
""".strip(), [
    "#include <iostream>",
])

# Test: Corrupted cout > fixed to cout <<
check("Fix corrupted 'cout >' to 'cout <<'", """
#include <iostream>
using namespace std;
int main() {
    cout > "Hello";
    return 0;
}
""".strip(), [
    'cout << "Hello"',
])

# Test: Corrupted cin < fixed to cin >>
check("Fix corrupted 'cin <' to 'cin >>'", """
#include <iostream>
using namespace std;
int main() {
    int n;
    cin < n;
    return 0;
}
""".strip(), [
    "cin >> n",
])

# Test: Missing return 0 gets added
check("Auto-add 'return 0;'", """
#include <iostream>
using namespace std;
int main() {
    cout << "Hello";
}
""".strip(), [
    "return 0;",
])

# Test: Missing braces get fixed
check("Auto-fix missing closing brace", """
#include <iostream>
using namespace std;
int main() {
    cout << "Hello";
""".strip(), [
    "}",
])

# Test: Vector include auto-added
check("Auto-add vector header", """
#include <iostream>
using namespace std;
int main() {
    vector<int> v = {1, 2, 3};
    sort(v.begin(), v.end());
    return 0;
}
""".strip(), [
    "#include <vector>",
    "#include <algorithm>",
])


# ══════════════════════════════════════════════════════════════
#  Test 2: Full response sanitization (simulates AI output)
# ══════════════════════════════════════════════════════════════

print()
print("=" * 60)
print(" BACKEND: Full response postprocessing")
print("=" * 60)

ai_response = """Here's the code for top 3 highest salary employees:

```cpp
#include <iostream>
#include <string>
#include <algorithm>
using namespace std;

struct Employee {
    string name;
    double salary;
};

int main() {
    int n;
    cout << "Enter number of employees: ";
    cin >> n;
    
    Employee employees[100];
    for (int i = 0; i < n; i++) {
        cout << "Enter name and salary: ";
        cin >> employees[i].name >> employees[i].salary;
    }
    
    // Sort by salary descending
    sort(employees, employees + n, [](const Employee& a, const Employee& b) {
        return a.salary > b.salary;
    });
    
    cout << "Top 3 highest paid:" << endl;
    for (int i = 0; i < min(3, n); i++) {
        cout << employees[i].name << " - $" << employees[i].salary << endl;
    }
    
    return 0;
}
```

This program reads employee data and displays the top 3."""

result = postprocess_codeme_response(ai_response)

critical_checks = [
    ("#include <iostream>", "iostream header"),
    ("#include <string>", "string header"),
    ("#include <algorithm>", "algorithm header"),
    ("cin >> n", "cin >> operator"),
    ("cout << ", "cout << operator"),
    ("i < n", "loop comparison"),
    ("cin >> employees[i].name >> employees[i].salary", "chained cin >>"),
    ("a.salary > b.salary", "comparison in lambda"),
    ("return 0;", "return statement"),
    ("int main()", "main function"),
]

for check_str, desc in critical_checks:
    if check_str in result:
        print(f"  ✓ PASS: {desc} — '{check_str}'")
        PASS += 1
    else:
        print(f"  ✗ FAIL: {desc} — '{check_str}' NOT FOUND")
        FAIL += 1


# ══════════════════════════════════════════════════════════════
#  Test 3: Frontend regex simulation (the ROOT CAUSE fix)
# ══════════════════════════════════════════════════════════════

print()
print("=" * 60)
print(" FRONTEND: Safe HTML regex simulation")
print("=" * 60)

# Simulate the OLD broken regex
def old_sanitize(code):
    """OLD broken version — strips ALL <...> patterns"""
    c = code
    c = re.sub(r'<span[^>]*>', '', c, flags=re.I)
    c = re.sub(r'</span>', '', c, flags=re.I)
    c = re.sub(r'<[^>]+>', '', c)  # ← THE KILLER
    return c

# Simulate the NEW safe regex
SAFE_HTML_TAGS = r'span|div|p|br|a|code|pre|em|strong|b|i|u|ul|ol|li|table|tr|td|th|h[1-6]|img|hr|section|article|nav|header|footer|main|mark|small|sub|sup|del|ins|blockquote|figure|figcaption|abbr|cite|dfn|kbd|samp|var|wbr|form|input|button|select|option|textarea|label|noscript|template|style|script|link|meta'
SAFE_HTML_RE = re.compile(r'</?(?:' + SAFE_HTML_TAGS + r')(?:\s[^>]*)?>', re.I)

def new_sanitize(code):
    """NEW safe version — only strips known HTML tags"""
    c = code
    c = re.sub(r'</?span[^>]*>', '', c, flags=re.I)
    c = SAFE_HTML_RE.sub('', c)
    return c

test_code = """#include <iostream>
#include <vector>
#include <algorithm>
using namespace std;

int main() {
    int n;
    cin >> n;
    vector<int> v(n);
    for (int i = 0; i < n; i++) {
        cin >> v[i];
    }
    sort(v.begin(), v.end());
    for (int i = 0; i < n; i++) {
        cout << v[i] << " ";
    }
    cout << endl;
    return 0;
}"""

old_result = old_sanitize(test_code)
new_result = new_sanitize(test_code)

# The OLD regex should DESTROY the code
old_broken_checks = [
    "#include <iostream>" not in old_result,  # stripped
    "#include <vector>" not in old_result,     # stripped
    "#include <algorithm>" not in old_result,   # stripped
]

print(f"  OLD regex strips #include headers: {'YES (broken)' if any(old_broken_checks) else 'No'}")

# The NEW regex should PRESERVE everything
new_checks = [
    ("#include <iostream>", "iostream header"),
    ("#include <vector>", "vector header"),
    ("#include <algorithm>", "algorithm header"),
    ("cin >> n", "cin >> operator"),
    ("cout << v[i]", "cout << operator"),
    ("i < n", "loop comparison"),
    ("vector<int>", "template syntax"),
    ("return 0;", "return statement"),
]

for check_str, desc in new_checks:
    if check_str in new_result:
        print(f"  ✓ PASS: NEW regex preserves {desc}")
        PASS += 1
    else:
        print(f"  ✗ FAIL: NEW regex broke {desc}")
        FAIL += 1

# Verify HTML tags ARE stripped by new regex
html_polluted = '<span class="hljs-keyword">int</span> main() { <em>test</em> }'
html_cleaned = new_sanitize(html_polluted)
if '<span' not in html_cleaned and '<em>' not in html_cleaned:
    print(f"  ✓ PASS: NEW regex still strips HTML tags")
    PASS += 1
else:
    print(f"  ✗ FAIL: NEW regex didn't strip HTML tags")
    FAIL += 1


# ══════════════════════════════════════════════════════════════
#  RESULTS
# ══════════════════════════════════════════════════════════════
print()
print("=" * 60)
total = PASS + FAIL
print(f" RESULTS: {PASS}/{total} passed, {FAIL} failed")
if FAIL == 0:
    print(" ✅ ALL TESTS PASSED — C++ code is compiler-safe!")
else:
    print(f" ❌ {FAIL} test(s) FAILED")
print("=" * 60)

sys.exit(0 if FAIL == 0 else 1)
