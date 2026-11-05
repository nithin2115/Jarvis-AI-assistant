from code_sanitizer import postprocess_codeme_response

out = postprocess_codeme_response(
    '```java\npublic <span class="hljs-keyword">class</span> X {}\n```'
)
assert "<span" not in out and "public class X" in out
print("sanitizer OK")
