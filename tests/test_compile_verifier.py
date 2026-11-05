"""Regression tests for compile_verifier.py."""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import compile_verifier


def _fence(code, lang="python"):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
def test_python_syntax_error():
    text = _fence("def f():\n    return x y", "python")
    ok, reason = compile_verifier.check("Solve it", text)
    assert ok is False
    assert "syntax" in reason.lower()


def test_python_indentation_error():
    text = _fence("def f():\nreturn 1", "python")
    ok, reason = compile_verifier.check("Solve it", text)
    assert ok is False
    assert "indentation" in reason.lower()


def test_python_missing_import():
    text = _fence("heap = heapq.heapify([1, 2])\nprint(collections.Counter([1]))", "python")
    ok, reason = compile_verifier.check("Solve it", text)
    assert ok is False
    assert "heapq" in reason
    assert "collections" in reason


def test_python_valid():
    text = _fence(
        "import heapq\nimport collections\n"
        "def f(nums):\n    return collections.Counter(nums)", "python"
    )
    ok, reason = compile_verifier.check("Solve it", text)
    assert ok is True
    assert reason == ""


def test_python_conceptual_passes():
    ok, reason = compile_verifier.check("Explain big-O", "It is a measure of complexity.")
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------
def test_java_multiple_public_classes():
    text = _fence("public class TrieNode {}\npublic class Trie {}", "java")
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "only one public" in reason.lower()


def test_java_unbalanced_braces():
    text = _fence("public class Main {\n    public static void main(String[] args) {\n        System.out.println(\"hi\");\n    }", "java")
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "unbalanced" in reason.lower()


def test_java_invalid_class_declaration():
    text = _fence("public class { }", "java")
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "invalid class" in reason.lower()


def test_java_missing_return():
    text = _fence(
        "public class Main {\n"
        "    public int add(int a, int b) {\n"
        "        int c = a + b;\n"
        "    }\n"
        "}", "java"
    )
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "return" in reason.lower()


def test_java_missing_import():
    text = _fence(
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        "        ArrayList<Integer> list = new ArrayList<>();\n"
        "        Scanner sc = new Scanner(System.in);\n"
        "    }\n"
        "}", "java"
    )
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "ArrayList" in reason
    assert "Scanner" in reason


def test_java_valid():
    text = _fence(
        "import java.util.ArrayList;\n"
        "import java.util.Scanner;\n"
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        "        ArrayList<Integer> list = new ArrayList<>();\n"
        "        Scanner sc = new Scanner(System.in);\n"
        "        System.out.println(list);\n"
        "    }\n"
        "}", "java"
    )
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# C++
# ---------------------------------------------------------------------------
def test_cpp_multiple_main():
    text = _fence("int main() { return 0; }\nint main() { return 1; }", "cpp")
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "main" in reason.lower()


def test_cpp_unbalanced_braces():
    text = _fence("int main() {\n    cout << \"hi\";\n", "cpp")
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "unbalanced" in reason.lower()


def test_cpp_missing_headers():
    text = _fence(
        "int main() {\n"
        "    vector<int> v = {1, 2};\n"
        "    cout << v[0] << endl;\n"
        "    return 0;\n"
        "}", "cpp"
    )
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is False
    assert "iostream" in reason
    assert "vector" in reason


def test_cpp_valid():
    text = _fence(
        "#include <iostream>\n"
        "#include <vector>\n"
        "using namespace std;\n"
        "int main() {\n"
        "    vector<int> v = {1, 2};\n"
        "    cout << v[0] << endl;\n"
        "    return 0;\n"
        "}", "cpp"
    )
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# Java semantic: referencing fields/methods a class does not declare
# ---------------------------------------------------------------------------
def test_java_undeclared_field_node_prev_next():
    # Node declares only key/value/freq but the code uses node.prev / node.next.
    text = _fence(
        "import java.util.HashMap;\n"
        "import java.util.Map;\n"
        "public class LFUCache {\n"
        "    class Node {\n"
        "        int key;\n"
        "        int value;\n"
        "        int freq;\n"
        "    }\n"
        "    Map<Integer, Node> keyToNode = new HashMap<>();\n"
        "    int minFreq;\n"
        "    void evict() {\n"
        "        Node node = keyToNode.get(minFreq);\n"
        "        node.prev.next = node.next;\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("implement an lfu cache", text)
    assert ok is False
    assert "prev" in reason.lower() or "next" in reason.lower()
    assert "node" in reason.lower()


def test_java_undeclared_method_rejected():
    text = _fence(
        "public class Box {\n"
        "    int value;\n"
        "    void run() {\n"
        "        Box b = new Box();\n"
        "        b.compute();\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("solve it", text)
    assert ok is False
    assert "compute" in reason.lower()


def test_java_declared_fields_pass():
    # Node declares prev/next, so accessing them is valid.
    text = _fence(
        "public class LFUCache {\n"
        "    class Node {\n"
        "        int key;\n"
        "        int value;\n"
        "        int freq;\n"
        "        Node prev;\n"
        "        Node next;\n"
        "    }\n"
        "    void touch(Node node) {\n"
        "        node.prev = node.next;\n"
        "        node.freq = node.freq + 1;\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("implement an lfu cache", text)
    assert ok is True, reason


def test_java_library_member_access_not_flagged():
    # HashMap is a library type; its members must never be flagged.
    text = _fence(
        "import java.util.HashMap;\n"
        "import java.util.Map;\n"
        "public class Solution {\n"
        "    public int run() {\n"
        "        Map<Integer, Integer> seen = new HashMap<>();\n"
        "        seen.put(1, 2);\n"
        "        return seen.getOrDefault(1, 0);\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("two sum", text)
    assert ok is True, reason


# ---------------------------------------------------------------------------
# Java semantic: undefined class instantiation
# ---------------------------------------------------------------------------
def test_java_undefined_class_rejected():
    text = _fence(
        "public class Solution {\n"
        "    public int run() {\n"
        "        Helper h = new Helper();\n"
        "        return h.size();\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("solve it", text)
    assert ok is False
    assert "helper" in reason.lower() and "undefined" in reason.lower()


def test_java_declared_class_instantiation_passes():
    text = _fence(
        "public class Solution {\n"
        "    class Helper {\n"
        "        int compute() { return 1; }\n"
        "    }\n"
        "    int run() {\n"
        "        Helper h = new Helper();\n"
        "        return h.compute();\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("solve it", text)
    assert ok is True, reason


def test_java_wildcard_import_disables_undefined_class():
    # With a wildcard import we cannot resolve names, so the undefined-class
    # check is skipped (conservative): `new Helper()` is NOT flagged.
    text = _fence(
        "import java.util.*;\n"
        "public class Solution {\n"
        "    int run() {\n"
        "        Helper h = new Helper();\n"
        "        return 0;\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("solve it", text)
    assert ok is True, reason


def test_java_known_jdk_class_not_flagged():
    text = _fence(
        "public class Solution {\n"
        "    int run() {\n"
        "        Random r = new Random();\n"
        "        return r.nextInt(10);\n"
        "    }\n"
        "}", "java")
    ok, reason = compile_verifier.check("solve it", text)
    assert ok is True, reason


# ---------------------------------------------------------------------------
# Python semantic: self.* attribute used but never assigned
# ---------------------------------------------------------------------------
def test_python_undefined_self_attr_rejected():
    text = _fence(
        "class Node:\n"
        "    def __init__(self, key, value):\n"
        "        self.key = key\n"
        "        self.value = value\n"
        "        self.freq = 1\n"
        "    def link(self):\n"
        "        return self.prev\n", "python")
    ok, reason = compile_verifier.check("implement an lfu cache", text)
    assert ok is False
    assert "prev" in reason.lower() and "node" in reason.lower()


def test_python_declared_self_attrs_pass():
    text = _fence(
        "class Node:\n"
        "    def __init__(self, key, value):\n"
        "        self.key = key\n"
        "        self.value = value\n"
        "        self.prev = None\n"
        "        self.next = None\n"
        "    def neighbours(self):\n"
        "        return self.prev, self.next\n", "python")
    ok, reason = compile_verifier.check("implement an lfu cache", text)
    assert ok is True, reason


def test_python_self_method_call_passes():
    text = _fence(
        "class Cache:\n"
        "    def __init__(self):\n"
        "        self.data = {}\n"
        "    def get(self, k):\n"
        "        return self._lookup(k)\n"
        "    def _lookup(self, k):\n"
        "        return self.data.get(k)\n", "python")
    ok, reason = compile_verifier.check("implement a cache", text)
    assert ok is True, reason


def test_python_inherited_class_skipped():
    # Base is unknown, so inherited attributes can't be resolved -> do NOT flag.
    text = _fence(
        "class Stack(list):\n"
        "    def peek(self):\n"
        "        return self.tail\n", "python")
    ok, reason = compile_verifier.check("implement a stack", text)
    assert ok is True, reason


# ---------------------------------------------------------------------------
# C++ semantic: member used but not declared on a user struct/class
# ---------------------------------------------------------------------------
def test_cpp_undeclared_member_rejected():
    text = _fence(
        "#include <unordered_map>\n"
        "using namespace std;\n"
        "struct Node {\n"
        "    int key;\n"
        "    int value;\n"
        "    int freq;\n"
        "};\n"
        "class LFUCache {\n"
        "    unordered_map<int, Node*> keyToNode;\n"
        "    int minFreq;\n"
        "    void evict() {\n"
        "        Node* node = keyToNode[minFreq];\n"
        "        node->prev = node->next;\n"
        "    }\n"
        "};", "cpp")
    ok, reason = compile_verifier.check("implement an lfu cache", text)
    assert ok is False
    assert "prev" in reason.lower() or "next" in reason.lower()
    assert "node" in reason.lower()


def test_cpp_declared_members_pass():
    text = _fence(
        "struct Node {\n"
        "    int key;\n"
        "    int value;\n"
        "    int freq;\n"
        "    Node* prev;\n"
        "    Node* next;\n"
        "};\n"
        "class LFUCache {\n"
        "    void touch(Node* node) {\n"
        "        node->prev = node->next;\n"
        "        node->freq = node->freq + 1;\n"
        "    }\n"
        "};", "cpp")
    ok, reason = compile_verifier.check("implement an lfu cache", text)
    assert ok is True, reason


def test_cpp_library_member_access_not_flagged():
    text = _fence(
        "#include <unordered_map>\n"
        "using namespace std;\n"
        "class Solution {\n"
        "public:\n"
        "    int run() {\n"
        "        unordered_map<int,int> seen;\n"
        "        seen.insert({1, 2});\n"
        "        return seen.count(1);\n"
        "    }\n"
        "};", "cpp")
    ok, reason = compile_verifier.check("two sum", text)
    assert ok is True, reason


# ---------------------------------------------------------------------------
# Mixed / edge cases
# ---------------------------------------------------------------------------
def test_no_code_blocks_pass():
    ok, reason = compile_verifier.check("Implement Trie", "Use a hash map for the children.")
    assert ok is True


def test_empty_code_block_pass():
    text = "```python\n\n```"
    ok, reason = compile_verifier.check("Implement Trie", text)
    assert ok is True


def test_critique_wrapper():
    assert compile_verifier.critique("Solve", "```python\ndef f():\nreturn 1\n```") == {"verified": False, "feedback": "Compile/syntax error: Python indentation error: expected an indented block after function definition on line 1 (line 2)."}


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
