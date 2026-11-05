# Code Review Knowledge Base

Critique FIRST, then ship complete refactored code. The refactor must preserve all
original behavior and must NOT be truncated (no `// TODO`, no "rest unchanged").

## Severity tagging
Label each finding **[Critical] / [Major] / [Minor] / [Nit]** so the author can triage.
Critical = security/correctness/data-loss; Major = perf or design that will bite at
scale; Minor/Nit = style and readability.

## Security (highest priority)
- **Injection**: SQL/NoSQL/command/LDAP — require parameterized queries / prepared
  statements; never string-concatenate untrusted input.
- **XSS / output encoding**: escape on render; avoid `innerHTML`/`dangerouslySetInnerHTML`.
- **AuthN/AuthZ**: every protected path checks identity AND role; no broken object-level
  authorization (IDOR).
- **Secrets**: no hard-coded keys/passwords/tokens; load from env/secret manager.
- **Crypto/passwords**: bcrypt/argon2 for passwords; no homemade crypto; validate TLS.
- **Input validation**: validate size/type/range server-side; treat all input as hostile.
- **Deserialization / SSRF / path traversal / open redirect**: validate and allowlist.

## Performance
- Algorithmic complexity: flag accidental O(n^2) (nested loops over the same data),
  and **N+1 queries** (query inside a loop) — batch / join / cache instead.
- Avoid needless allocations/copies in hot paths; stream large data.
- Use proper indexes for query predicates; paginate unbounded result sets.
- Concurrency: data races, missing synchronization, blocking calls on hot threads.

## Correctness & robustness
- Edge cases: null/empty, boundaries, negative/overflow, timezones, encoding.
- Error handling: no swallowed exceptions; fail fast with context; clean up resources
  (try-with-resources / context managers / `finally`).
- Idempotency and retries for external calls; sensible timeouts.

## Maintainability
- Naming reveals intent; functions do one thing; respect SRP and DRY.
- Reduce cognitive complexity (deep nesting -> early returns / guard clauses).
- Remove dead code and misleading comments; comments explain WHY, not WHAT.
- Keep the public API small and cohesive; separate concerns (no logic in controllers).

## The refactor
- Provide the COMPLETE, runnable refactored code — preserve behavior, fix the findings,
  no placeholders or truncation.
- Prefer the smallest change that resolves the issue; don't gratuitously rewrite.
- Call out any behavior change explicitly and add/adjust tests for it.
