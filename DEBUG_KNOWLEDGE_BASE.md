# Debugging Knowledge Base

Evidence-first debugging. NEVER fabricate the user's code, stack trace, or a "fixed"
file you cannot see. If the failing code and FULL stack trace are missing, ask for them.

## Always request (Evidence Needed)
- The FULL stack trace, including `Caused by:` chains and the first frame in the user's
  own package/file.
- The exact failing code (method/class/function), not a paraphrase.
- Language + runtime version, build tool, and relevant config/env.
- The minimal input that reproduces it, and whether it's deterministic or intermittent.

## Read the trace top-down
- The top frame names the file + line where it threw; the bottom is the entry point.
- `Caused by:` reveals the original error behind a wrapped exception — chase it.
- The exception TYPE narrows the cause before you ever see the code.

## Common errors -> specific likely causes
- **NullPointerException / None** -> uninitialized field, method returned null,
  missing dependency injection, autounboxing a null `Integer`, map miss.
- **IndexOutOfBounds / off-by-one** -> `<=` vs `<`, empty collection, stale length.
- **ClassNotFound / NoSuchMethod / ImportError** -> dependency/version mismatch,
  classpath/module path, shaded jars, circular import.
- **Segfault / access violation (C/C++/native)** -> dangling/null pointer, buffer
  overrun, use-after-free, bad FFI/JNI signature.
- **StackOverflowError** -> unbounded recursion / missing base case.
- **OutOfMemory** -> leak (retained references, growing cache), too-small heap,
  loading huge payloads into memory.
- **Deadlock / hang** -> lock ordering, blocking call on the event/UI thread,
  unclosed resources, thread-pool starvation.
- **Race / flaky** -> shared mutable state without synchronization, check-then-act,
  reliance on timing.
- **HTTP 500 / 401 / 403 / 404 / CORS** -> unhandled server exception, missing/expired
  token, role check, wrong route, server-side CORS config.

## Isolation technique
- Reproduce minimally, then bisect (git bisect / comment-halving) to the smallest
  failing case. Add targeted logging of the exact references on the failing line.
- Form a falsifiable hypothesis, test ONE variable at a time, confirm before fixing.

## Fixes
- If the user provided code, give the corrected snippet for THAT code.
- If not, give the fix PATTERN (null check / `Optional` / defensive init / parameterized
  query / proper synchronization) without inventing their code.
- Address the root cause, not the symptom; note any regression test to add.
