# Full Stack Build Standards

Production conventions for generated full-stack projects. BUILD real, complete,
runnable files — never tutorials, never truncated stubs.

## Mandatory project layout
Every project ships these top-level directories:
```text
project/
  frontend/        # React app (components, hooks, state, API client)
  backend/         # API service (Spring Boot / Node / Django ...)
  database/        # schema.sql + migrations + seed data
  docker/          # Dockerfile(s) + docker-compose.yml wiring the whole stack
```

## Backend layering (clean architecture)
- **Entities / Models** — the persistent data model (JPA `@Entity`, ORM models).
- **Repositories / DAOs** — data access only; no business logic.
- **Services** — business logic, transactions, validation; depend on repositories.
- **Controllers / Routes** — thin HTTP layer mapping requests to services; validate
  input, return proper status codes, never embed business logic.
- Use DTOs at the boundary; do not leak entities directly to the client.

## Frontend
- Function components + hooks; lift shared state sensibly (context/store).
- A single API client module; no hard-coded URLs scattered in components.
- Handle loading, empty, and error states for every async view.

## API & data
- RESTful resource naming, correct verbs/status codes (201 create, 204 delete,
  400 validation, 401/403 auth, 404 missing, 409 conflict).
- Validate and sanitize all input server-side; never trust the client.
- `database/` contains real DDL (tables, keys, indexes) and migrations — not prose.

## Security (non-negotiable)
- AuthN with JWT or sessions; AuthZ with role checks (RBAC) on protected routes.
- Hash passwords (bcrypt/argon2). NEVER store plaintext secrets.
- Secrets via environment variables / `.env` (git-ignored) — never hard-coded.
- Parameterized queries / ORM to prevent SQL injection; enable CORS deliberately.

## Docker / runnability
- A `Dockerfile` for frontend and backend, plus `docker-compose.yml` that wires
  frontend + backend + database (and cache/queue if used) with healthchecks and a
  shared network. The stack must come up with a single `docker compose up`.
- Pin base image versions; use multi-stage builds for slim production images.

## Quality bar
- Every file is COMPLETE: no `// TODO`, no `... (omitted)`, no "rest of the code".
- Include dependency manifests (`package.json`, `pom.xml`/`build.gradle`/
  `requirements.txt`) consistent with the code's imports.
- A concise README: install, run, and the available endpoints.
- Prefer minimal but working tests for core endpoints where practical.

## Production-grade build checklist (ENFORCED — deterministic critic)
No dependency-only implementations, no placeholders, no pseudo-code. If you NAME a
technology you MUST ship its full, runnable implementation. Each rule below is
gated on the trigger tech actually being used:

- **JWT auth (if JWT is used):** a `JwtFilter` (extends `OncePerRequestFilter`), a
  `JwtUtil`/token provider, explicit token validation (`validateToken`), and reading
  the `Authorization: Bearer` header. Partial JWT is rejected.
- **Redis (if Redis is used):** a `RedisConfig` (connection + `@EnableCaching`), a
  `RedisTemplate`/`CacheManager`, real cache reads/writes (`@Cacheable`), and an
  invalidation/TTL strategy (`@CacheEvict`/`expire`).
- **Kafka (if Kafka is used):** a producer (`KafkaTemplate.send`), a `@KafkaListener`
  consumer, explicit topic definitions (`NewTopic`/`@EnableKafka`), and the event
  payload + (de)serialization.
- **E-commerce systems:** the full commerce data model — `Cart`, `CartItem`,
  `OrderItem`, `Payment`, and `Inventory` entities — not just `Product`/`Order`.
- **Spring Security:** configure a `SecurityFilterChain` `@Bean` (component-based).
  NEVER use the removed `WebSecurityConfigurerAdapter`.
- **Docker:** a real `Dockerfile` (multi-stage, pinned base) AND a `docker-compose.yml`
  wiring frontend + backend + database (+ cache/queue if used).
- **React frontend:** `pages/`, reusable `components/`, an API `services/` client,
  client-side `routing` (react-router), and live API integration (axios/fetch).
- **API docs:** if you advertise API documentation, ship the Swagger/OpenAPI config
  (`springdoc-openapi`, `swagger-ui`) — do not just claim it exists.
- **Production readiness (every build):** a DTO layer at the API boundary, a
  `@ControllerAdvice` `GlobalExceptionHandler`, bean-validation annotations
  (`@Valid`/`@NotNull`/`@NotBlank`), and a logging strategy (SLF4J / equivalent).
