"""
Phase 6 — Full Stack / Project Builder critic + standards regression suite.

Deterministic tests for folder-structure + truncation enforcement, the
single-component escape hatch, and verifier short-circuit behavior. Run:
    python -m pytest tests/test_fullstack.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.disable(logging.CRITICAL)

import fullstack_critic as fc

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _block(code, lang=""):
    return f"```{lang}\n{code}\n```"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
TREE = _block("todo-app/\n  frontend/\n  backend/\n  database/\n  docker/", "text")

COMPLETE_PROJECT = (
    "### Folder Structure\n" + TREE + "\n\n"
    "### Entities\n" + _block(
        "@Entity\npublic class Todo {\n  @Id @GeneratedValue Long id;\n  @NotBlank String title;\n  boolean done;\n}", "java") + "\n\n"
    "### DTOs\n" + _block(
        "public record TodoRequest(@NotBlank String title) {}\n"
        "public record TodoResponse(Long id, String title, boolean done) {}", "java") + "\n\n"
    "### Repositories\n" + _block(
        "public interface TodoRepository extends JpaRepository<Todo, Long> {}", "java") + "\n\n"
    "### Services\n" + _block(
        "@Service\npublic class TodoService {\n"
        "  private static final Logger log = LoggerFactory.getLogger(TodoService.class);\n"
        "  private final TodoRepository repo;\n"
        "  public TodoService(TodoRepository repo){ this.repo = repo; }\n"
        "  public List<TodoResponse> all(){ log.info(\"list\"); return repo.findAll().stream()"
        ".map(t -> new TodoResponse(t.getId(), t.getTitle(), t.isDone())).toList(); }\n}", "java") + "\n\n"
    "### Controllers\n" + _block(
        "@RestController\n@RequestMapping(\"/api/todos\")\npublic class TodoController {\n"
        "  private final TodoService svc;\n"
        "  public TodoController(TodoService svc){ this.svc = svc; }\n"
        "  @GetMapping List<TodoResponse> all(){ return svc.all(); }\n"
        "  @PostMapping TodoResponse create(@Valid @RequestBody TodoRequest req){ return svc.create(req); }\n}", "java") + "\n\n"
    "### Exception Handling\n" + _block(
        "@RestControllerAdvice\npublic class GlobalExceptionHandler {\n"
        "  @ExceptionHandler(MethodArgumentNotValidException.class)\n"
        "  ResponseEntity<String> handle(MethodArgumentNotValidException e){ return ResponseEntity.badRequest().body(e.getMessage()); }\n}", "java") + "\n\n"
    "### React Components\n" + _block(
        "// frontend/src/services/api.js\nimport axios from 'axios';\n"
        "export const api = axios.create({ baseURL: '/api' });\nexport const getTodos = () => api.get('/todos');", "jsx") + "\n"
    + _block(
        "// frontend/src/pages/TodoPage.jsx\nimport { useEffect, useState } from 'react';\n"
        "import { getTodos } from '../services/api';\nimport TodoList from '../components/TodoList';\n"
        "export default function TodoPage(){\n  const [todos, setTodos] = useState([]);\n"
        "  useEffect(() => { getTodos().then(r => setTodos(r.data)); }, []);\n  return <TodoList items={todos} />;\n}", "jsx") + "\n"
    + _block(
        "// frontend/src/App.jsx\nimport { BrowserRouter, Routes, Route } from 'react-router-dom';\n"
        "import TodoPage from './pages/TodoPage';\nexport default function App(){\n"
        "  return (<BrowserRouter><Routes><Route path='/' element={<TodoPage/>} /></Routes></BrowserRouter>);\n}", "jsx") + "\n\n"
    "### Docker Files\n" + _block(
        "# docker/backend.Dockerfile\nFROM eclipse-temurin:21-jre\nCOPY app.jar /app.jar\nENTRYPOINT [\"java\",\"-jar\",\"/app.jar\"]", "docker") + "\n"
    + _block(
        "services:\n  backend:\n    build: ../backend\n  frontend:\n    build: ../frontend\n  db:\n    image: postgres:16", "yaml") + "\n\n"
    "### README\nInstall deps, run with docker compose up, then call the /api/todos endpoints.\n"
)

MISSING_DOCKER = (
    "### Folder Structure\n" + _block("app/\n  frontend/\n  backend/\n  database/", "text") + "\n\n"
    "### Entities\n" + _block("class User: pass", "python") + "\n\n"
    "### Services\n" + _block("def create_user(): ...", "python") + "\n"
)

TRUNCATED = (
    "### Folder Structure\n" + TREE + "\n\n"
    "### Services\n" + _block("class Svc {\n  // TODO: implement business logic\n}", "java") + "\n\n"
    "### Controllers\n" + _block("class Ctrl {}", "java") + "\n"
)

PROSE_PROJECT = (
    "### Folder Structure\n" + TREE + "\n\n"
    "### Entities\nYou would create a Todo entity with id and title fields.\n\n"
    "### Services\nThe service layer would handle the business logic for todos.\n"
)

SINGLE_COMPONENT = (
    "Here is the component:\n" + _block(
        "export default function Counter(){\n"
        "  const [n, setN] = useState(0);\n"
        "  return <button onClick={() => setN(n + 1)}>{n}</button>;\n}", "jsx")
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_dir_present_slash_form():
    assert fc._dir_present("frontend", "  frontend/   # react") is True
    assert fc._dir_present("docker", "no docker here") is False


def test_is_project_build_detection():
    assert fc._is_project_build(COMPLETE_PROJECT) is True
    assert fc._is_project_build(SINGLE_COMPONENT) is False


# ---------------------------------------------------------------------------
# Enforcement (full-project builds)
# ---------------------------------------------------------------------------
def test_complete_project_passes():
    assert fc.critique("Build a Spring Boot + React todo app", COMPLETE_PROJECT)["verified"] is True


def test_missing_docker_rejected():
    r = fc.critique("Build a MERN todo app", MISSING_DOCKER)
    assert r["verified"] is False
    assert "docker/" in r["feedback"].lower()


def test_truncated_code_rejected():
    r = fc.critique("Build a todo app", TRUNCATED)
    assert r["verified"] is False
    assert "incomplete" in r["feedback"].lower() or "todo" in r["feedback"].lower()


def test_prose_only_project_rejected():
    r = fc.critique("Build a todo app", PROSE_PROJECT)
    assert r["verified"] is False
    assert "build" in r["feedback"].lower() or "code" in r["feedback"].lower()


# ---------------------------------------------------------------------------
# Escape hatch: single-component / narrow requests are NOT force-templated
# ---------------------------------------------------------------------------
def test_single_component_defers():
    assert fc.critique("Create a React component for the frontend", SINGLE_COMPONENT)["verified"] is True


def test_clarification_defers():
    text = "Which stack would you like — MERN, or Spring Boot + React?"
    assert fc.critique("Build me an app", text)["verified"] is True


# ---------------------------------------------------------------------------
# Verifier integration (reject paths short-circuit BEFORE any LLM call)
# ---------------------------------------------------------------------------
def test_verifier_rejects_missing_docker_without_network():
    import verifier_agent
    r = verifier_agent.verify("PROJECT_BUILDER_AGENT", "Build a MERN todo app", MISSING_DOCKER)
    assert r["verified"] is False


def test_verifier_rejects_truncated_fullstack_without_network():
    import verifier_agent
    r = verifier_agent.verify("FULLSTACK_AGENT", "Build a todo app", TRUNCATED)
    assert r["verified"] is False


def test_verifier_passes_complete_project(monkeypatch):
    import brain_manager
    import verifier_agent
    monkeypatch.setattr(brain_manager, "ask", lambda *a, **k: ("VERIFIED", "fake"))
    r = verifier_agent.verify("PROJECT_BUILDER_AGENT",
                              "Build a Spring Boot + React todo app", COMPLETE_PROJECT)
    assert r["verified"] is True


# ---------------------------------------------------------------------------
# Knowledge base wiring (standards injected into BOTH builder agents)
# ---------------------------------------------------------------------------
def test_fullstack_standards_file_exists():
    assert os.path.exists(os.path.join(BASE, "FULLSTACK_STANDARDS.md"))


def test_fullstack_standards_injected_into_both_agents():
    import router
    for agent in (router.PROJECT_BUILDER_AGENT, router.FULLSTACK_AGENT):
        prompt = router.AGENT_PROMPTS[agent].lower()
        assert "clean architecture" in prompt
        assert "docker compose up" in prompt


# ===========================================================================
# Production-grade conditional checks (Phase 6 hardening).
# Each check is gated on the trigger tech, so narrow requests stay green.
# ===========================================================================
def _proj(body):
    return "### Folder Structure\n" + TREE + "\n\n" + body


JWT_INCOMPLETE = _proj(
    "### Security\nWe secure endpoints with JWT.\n" + _block(
        "@RestController\nclass AuthController { @PostMapping(\"/login\") String login(){ return \"x\"; } }", "java"))

JWT_COMPLETE = COMPLETE_PROJECT + "\n### Security\n" + _block(
    "@Component\npublic class JwtFilter extends OncePerRequestFilter {\n"
    "  private final JwtUtil jwtUtil;\n"
    "  protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain){\n"
    "    String header = req.getHeader(\"Authorization\");\n"
    "    if (header != null && header.startsWith(\"Bearer \")) {\n"
    "      String token = header.substring(7);\n"
    "      if (jwtUtil.validateToken(token)) { /* authenticate */ }\n"
    "    }\n  }\n}", "java") + "\n" + _block(
    "@Configuration\npublic class SecurityConfig {\n"
    "  @Bean SecurityFilterChain chain(HttpSecurity http) throws Exception { return http.build(); }\n}", "java")

REDIS_INCOMPLETE = _proj(
    "### Caching\nWe use Redis to cache products.\n" + _block(
        "@Service\nclass ProductService { List<String> all(){ return List.of(); } }", "java"))

KAFKA_INCOMPLETE = _proj(
    "### Messaging\nWe use Kafka for async order events.\n" + _block(
        "@Service\nclass OrderService { void place(){} }", "java"))

ECOMMERCE_INCOMPLETE = _proj(
    "### Entities\n" + _block(
        "@Entity class Product { Long id; String name; }\n@Entity class Order { Long id; }", "java"))

DEPRECATED_SECURITY = _proj(
    "### Security\n" + _block(
        "@Configuration\nclass SecurityConfig extends WebSecurityConfigurerAdapter {\n"
        "  protected void configure(HttpSecurity http){} }", "java"))

SECURITY_NO_FILTERCHAIN = _proj(
    "### Security\nEnable Spring Security with a password encoder.\n" + _block(
        "@Configuration\n@EnableWebSecurity\nclass SecurityConfig { @Bean PasswordEncoder pe(){ return new BCryptPasswordEncoder(); } }", "java"))

DOCKER_NO_DOCKERFILE = _proj(
    "### Services\n" + _block("@Service\nclass S { void go(){} }", "java") +
    "\n### Docker Files\n" + _block("services:\n  db:\n    image: postgres:16", "yaml"))

REACT_INCOMPLETE = _proj(
    "### React Components\n" + _block(
        "export default function App(){ return <div>Hello</div>; }", "jsx") +
    "\n### Docker Files\n" + _block("# Dockerfile\nFROM node:20\nservices:\n  web:\n    build: .", "docker"))

SWAGGER_MISSING = _proj(
    "### Services\n" + _block("@Service\nclass S { void go(){} }", "java") +
    "\n### Docker Files\n" + _block("# Dockerfile\nFROM x\nservices:\n  db:\n    image: postgres", "docker") +
    "\n### README\nInteractive API documentation is available for all endpoints.\n")

PROD_MISSING = _proj(
    "### Services\n" + _block("@Service\nclass S { void go(){ } }", "java") +
    "\n### Docker Files\n" + _block("# Dockerfile\nFROM x\nservices:\n  db:\n    image: postgres", "docker"))


# ── helper-level checks ─────────────────────────────────────────────────────
def test_wants_react_detection():
    assert fc._wants_react("Build a React app", "") is True
    assert fc._wants_react("", "export default function App(){}") is True
    assert fc._wants_react("Build a CLI tool", "package main") is False


def test_is_ecommerce_detection():
    assert fc._is_ecommerce("Build an online store", "") is True
    assert fc._is_ecommerce("Build an e-commerce shop", "") is True
    assert fc._is_ecommerce("Build a todo app", "@Entity class Todo {}") is False


# ── conditional reject paths ────────────────────────────────────────────────
def test_jwt_incomplete_rejected():
    r = fc.critique("Build a secure API with JWT", JWT_INCOMPLETE)
    assert r["verified"] is False and "jwt" in r["feedback"].lower()


def test_jwt_complete_passes():
    assert fc.critique("Build a Spring Boot + React app with JWT", JWT_COMPLETE)["verified"] is True


def test_redis_incomplete_rejected():
    r = fc.critique("Build an API with Redis caching", REDIS_INCOMPLETE)
    assert r["verified"] is False and "redis" in r["feedback"].lower()


def test_kafka_incomplete_rejected():
    r = fc.critique("Build an event-driven app with Kafka", KAFKA_INCOMPLETE)
    assert r["verified"] is False and "kafka" in r["feedback"].lower()


def test_ecommerce_missing_entities_rejected():
    r = fc.critique("Build an online store e-commerce app", ECOMMERCE_INCOMPLETE)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "cart" in fb and "payment" in fb and "inventory" in fb


def test_deprecated_websecurityconfigureradapter_rejected():
    r = fc.critique("Build an app with login", DEPRECATED_SECURITY)
    assert r["verified"] is False and "websecurityconfigureradapter" in r["feedback"].lower()


def test_security_without_filterchain_rejected():
    r = fc.critique("Build an app with Spring Security", SECURITY_NO_FILTERCHAIN)
    assert r["verified"] is False and "securityfilterchain" in r["feedback"].lower()


def test_docker_without_dockerfile_rejected():
    r = fc.critique("Build and dockerize a service", DOCKER_NO_DOCKERFILE)
    assert r["verified"] is False and "dockerfile" in r["feedback"].lower()


def test_react_incomplete_rejected():
    r = fc.critique("Build a React frontend", REACT_INCOMPLETE)
    assert r["verified"] is False and "react" in r["feedback"].lower()


def test_swagger_advertised_but_missing_rejected():
    r = fc.critique("Build a backend API", SWAGGER_MISSING)
    assert r["verified"] is False
    assert "swagger" in r["feedback"].lower() or "openapi" in r["feedback"].lower()


def test_production_readiness_missing_rejected():
    r = fc.critique("Build a backend service", PROD_MISSING)
    assert r["verified"] is False
    fb = r["feedback"].lower()
    assert "dto" in fb or "globalexceptionhandler" in fb or "validation" in fb or "logging" in fb


# ── verifier integration (deterministic reject, no network) ─────────────────
def test_verifier_rejects_incomplete_jwt_without_network():
    import verifier_agent
    r = verifier_agent.verify("PROJECT_BUILDER_AGENT", "Build a secure API with JWT", JWT_INCOMPLETE)
    assert r["verified"] is False


def test_verifier_rejects_ecommerce_missing_entities_without_network():
    import verifier_agent
    r = verifier_agent.verify("FULLSTACK_AGENT", "Build an online store", ECOMMERCE_INCOMPLETE)
    assert r["verified"] is False


def test_builder_standards_carry_production_guidance():
    import router
    for agent in (router.PROJECT_BUILDER_AGENT, router.FULLSTACK_AGENT):
        prompt = router.AGENT_PROMPTS[agent].lower()
        for token in ("jwtfilter", "securityfilterchain", "globalexceptionhandler",
                      "redistemplate", "@kafkalistener", "swagger"):
            assert token in prompt, f"{agent} missing builder guidance: {token!r}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
