"""Deterministic Full Stack / Project Builder critic (Phase 6).

Mechanically enforces the two things the LLM verifier is unreliable at for a project
build: the mandatory top-level folder layout and the absence of truncated / placeholder
code. It runs before the LLM verifier for the PROJECT_BUILDER and FULLSTACK agents.

Conservative gating (never reject a correct answer):
  * Enforcement only triggers for a FULL-PROJECT build — a response that ships a
    Folder/Project Structure or names >= 2 of the four mandated directories. A narrow
    request (e.g., "create a React component") is deferred to the LLM verifier and is
    NOT forced into the full frontend/backend/database/docker layout.
  * Truncation detection uses specific placeholder phrases, not bare "..." (which is
    common and legitimate inside directory trees).
"""
import logging
import re

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.DOTALL)
_DIRS = ("frontend", "backend", "database", "docker")


def _has(text, pattern):
    return bool(re.search(pattern, text or "", re.IGNORECASE))


def _mentioned(text, *words):
    return any(_has(text, r"\b" + w + r"\b") for w in words)


# (label, regex) requirements that apply ONLY when the trigger tech is present.
_JWT_REQS = [
    ("JwtFilter (request filter)", r"jwt\s*filter|jwtauthenticationfilter|onceperrequestfilter"),
    ("JwtUtil / token provider", r"jwt\s*util|jwt\s*provider|jwttokenprovider|tokenprovider"),
    ("token validation", r"validate\s*token|validatejwt|parseclaims|verify(?:ing)?\s*(?:the\s*)?token|istokenvalid"),
    ("Authorization header flow", r"authorization\s*header|bearer\b|getheader\(\s*[\"']authorization"),
]
_REDIS_REQS = [
    ("RedisConfig", r"redis\s*config|redisconfiguration|@enablecaching|lettuceconnectionfactory|jedisconnectionfactory"),
    ("RedisTemplate / cache manager", r"redis\s*template|cachemanager|rediscachemanager|@cacheable"),
    ("cache read/write usage", r"@cacheable|opsforvalue|opsforhash|\.set\(|\.get\(|cache\.put|cache\.get"),
    ("cache invalidation strategy", r"@cacheevict|invalidat|\.delete\(|evict|ttl|expire|time\s*to\s*live"),
]
_KAFKA_REQS = [
    ("Kafka producer", r"kafka\s*template|kafkaproducer|@?producer\b|\.send\("),
    ("Kafka consumer", r"@kafkalistener|kafkaconsumer|@?consumer\b|@streamlistener"),
    ("topic definition", r"topic\b|newtopic|@enablekafka|topicbuilder"),
    ("event flow / payload", r"event\b|payload|message\b|serializ|deserializ"),
]
_ECOMMERCE_ENTITIES = [
    ("Cart", r"\bcart\b"),
    ("CartItem", r"cart\s*item|cartitem"),
    ("OrderItem", r"order\s*item|orderitem|line\s*item"),
    ("Payment", r"\bpayment\b"),
    ("Inventory", r"\binventory\b|\bstock\b"),
]
_REACT_REQS = [
    ("pages", r"\bpages?\b|/pages/|routes/|views?/"),
    ("components", r"\bcomponents?\b|/components/"),
    ("services / API client", r"\bservices?\b|api\s*client|/services/|/api/|axios|fetch\("),
    ("routing", r"react-router|browserrouter|<routes?\b|createbrowserrouter|<Route\b|usenavigate"),
    ("API integration", r"axios|fetch\(|useeffect\([^)]*\b(?:fetch|axios|api)|api\.(?:get|post|put|delete)"),
]
_PROD_REQS = [
    ("DTO layer", r"\bdto\b|data\s*transfer\s*object|request\s*dto|response\s*dto|\w+request\b|\w+response\b"),
    ("GlobalExceptionHandler", r"@controlleradvice|@restcontrolleradvice|globalexceptionhandler|@exceptionhandler"),
    ("validation annotations", r"@valid\b|@notnull|@notblank|@size|@email|@min\b|@max\b|jakarta\.validation|javax\.validation|class-validator|express-validator|\bjoi\b|\bzod\b|\byup\b|@isstring|@isnotempty"),
    ("logging strategy", r"\blogger\b|loggerfactory|slf4j|@slf4j|logging\.|winston|pino|log\.(?:info|error|warn|debug)"),
]

# Placeholder / truncation markers that mean the code is NOT complete.
_TRUNCATION = re.compile(
    r"(//\s*TODO|#\s*TODO|\bTODO:|omitted for brevity|"
    r"rest of (?:the |your )?(?:code|implementation|files?)|"
    r"your code (?:goes )?here|implementation (?:goes )?here|"
    r"\(\s*\.\.\.\s*\)|\.\.\.\s*\(truncated\)|and so on\b)",
    re.IGNORECASE,
)


def _code_blocks(text: str):
    return [m.group(1) for m in _FENCE.finditer(text or "")]


def _dir_present(name: str, text: str) -> bool:
    """A directory is present if it appears in the mandated `name/` slash form."""
    return bool(re.search(r"\b" + name + r"\s*/", text or "", re.IGNORECASE))


def _is_project_build(text: str) -> bool:
    """True when the response purports to be a full multi-layer project build."""
    low = (text or "").lower()
    if "folder structure" in low or "project structure" in low:
        return True
    return sum(_dir_present(d, text) for d in _DIRS) >= 2


def _reject(area, missing, fix):
    logger.warning(f"[FULLSTACK_CRITIC] {area} incomplete; missing: {missing}")
    return {"verified": False, "feedback": (
        f"{area} is incomplete \u2014 missing: {', '.join(missing)}. " + fix +
        " No dependency-only stubs, placeholders, or pseudo-code; ship complete, runnable files."
    )}


def _is_ecommerce(query, text):
    blob = (query or "") + "\n" + (text or "")
    return _mentioned(blob, "ecommerce", "e-commerce", "shop", "store", "marketplace",
                      "checkout") or _has(blob, r"\bamazon\b|\bflipkart\b|online\s+store|shopping\s*cart")


def _wants_react(query, text):
    return _mentioned(query, "react") or _mentioned(text, "react") or _has(
        text, r"\.(?:jsx|tsx)\b|usestate|useeffect|export\s+default\s+function|reactdom")


def _wants_security(text):
    return _has(text, r"@enablewebsecurity|spring\s*security|securityfilterchain|"
                      r"websecurityconfigureradapter|authenticationmanager|userdetailsservice|"
                      r"\bjwt\b|passwordencoder|bcrypt")


def critique(user_query: str, response_text: str) -> dict:
    """Return {"verified": bool, "feedback": str}. Deterministic only."""
    text = response_text or ""

    # Narrow / single-file requests are not forced into the full project layout.
    if not _is_project_build(text):
        return {"verified": True, "feedback": ""}

    missing = [d for d in _DIRS if not _dir_present(d, text)]
    if missing:
        logger.warning(f"[FULLSTACK_CRITIC] Missing mandatory directories: {missing}")
        return {"verified": False, "feedback": (
            "The Folder Structure must explicitly include all four top-level "
            "directories: frontend/, backend/, database/, and docker/. "
            f"Missing: {', '.join(d + '/' for d in missing)}."
        )}

    if len(_code_blocks(text)) < 2:
        logger.warning("[FULLSTACK_CRITIC] Project build with too little real code")
        return {"verified": False, "feedback": (
            "BUILD the project: ship real, complete code files for the layers "
            "(Entities, Repositories, Services, Controllers, React Components, Docker "
            "Files) in fenced code blocks — not prose or a tutorial."
        )}

    m = _TRUNCATION.search(text)
    if m:
        logger.warning(f"[FULLSTACK_CRITIC] Truncated/placeholder code: {m.group(0)!r}")
        return {"verified": False, "feedback": (
            f"Code is incomplete — found a placeholder/truncation marker "
            f"('{m.group(0).strip()}'). Generate every file in full: no TODO, no "
            f"'omitted for brevity', no 'rest of the code'."
        )}

    # ── Conditional production-grade checks (full builds only) ──────────────
    q = user_query or ""

    def _missing(reqs):
        return [label for label, pat in reqs if not _has(text, pat)]

    # JWT: if the build advertises JWT auth, the full flow must be present.
    if _mentioned(text, "jwt") or _has(text, r"json\s*web\s*token"):
        miss = _missing(_JWT_REQS)
        if miss:
            return _reject("JWT authentication", miss,
                "Wire the real auth flow: a JwtFilter/OncePerRequestFilter, a "
                "JwtUtil/token provider, explicit token validation, and reading the "
                "Authorization: Bearer header.")

    # Redis: caching must be configured AND used, with invalidation.
    if _mentioned(text, "redis"):
        miss = _missing(_REDIS_REQS)
        if miss:
            return _reject("Redis caching", miss,
                "Ship a RedisConfig (connection + @EnableCaching), a RedisTemplate/"
                "CacheManager, real cache reads/writes, and an invalidation/TTL strategy.")

    # Kafka: producer + consumer + topic + event flow.
    if _mentioned(text, "kafka"):
        miss = _missing(_KAFKA_REQS)
        if miss:
            return _reject("Kafka messaging", miss,
                "Implement a producer (KafkaTemplate.send), a @KafkaListener consumer, "
                "explicit topic definitions, and the event payload/serialization.")

    # E-commerce: the core commerce entities must exist.
    if _is_ecommerce(q, text):
        miss = [label for label, pat in _ECOMMERCE_ENTITIES if not _has(text, pat)]
        if miss:
            return _reject("E-commerce data model", miss,
                "Model the full commerce domain with Cart, CartItem, OrderItem, Payment, "
                "and Inventory entities — not just Product/Order.")

    # Spring Security: deprecated base class banned; SecurityFilterChain required.
    if _has(text, r"websecurityconfigureradapter"):
        return {"verified": False, "feedback": (
            "Remove WebSecurityConfigurerAdapter — it was removed in Spring Security 6. "
            "Configure a SecurityFilterChain @Bean (component-based security) instead."
        )}
    if _wants_security(text) and not _has(text, r"securityfilterchain"):
        return {"verified": False, "feedback": (
            "Spring Security is configured but no SecurityFilterChain @Bean is defined. "
            "Use the modern SecurityFilterChain component-based configuration."
        )}

    # Docker: a real Dockerfile AND a docker-compose wiring the stack.
    if not _has(text, r"dockerfile"):
        return {"verified": False, "feedback": (
            "Docker is required but no Dockerfile is present. Add a Dockerfile for the "
            "backend (and frontend) — multi-stage, pinned base image."
        )}
    if not _has(text, r"docker[-\s]?compose|compose\.ya?ml|services:\s"):
        return {"verified": False, "feedback": (
            "Docker is required but no docker-compose is present. Add a docker-compose.yml "
            "wiring frontend + backend + database (and cache/queue if used)."
        )}

    # React frontend: pages, components, services, routing, API integration.
    if _wants_react(q, text):
        miss = _missing(_REACT_REQS)
        if miss:
            return _reject("React frontend", miss,
                "Build a real SPA: pages, reusable components, an API service/client "
                "layer, client-side routing (react-router), and live API integration.")

    # Swagger: if API docs are advertised, the config must actually exist.
    if _has(text, r"api\s*docs|api\s*documentation|swagger|openapi") and not _has(
            text, r"springdoc|swagger-ui|@openapidefinition|openapi\s*\(\)|springfox|"
                  r"swaggerconfig|/v3/api-docs|/swagger-ui"):
        return {"verified": False, "feedback": (
            "API documentation is advertised but no Swagger/OpenAPI configuration is "
            "present. Add springdoc-openapi (or equivalent) and expose swagger-ui."
        )}

    # Production readiness (every full build).
    miss = _missing(_PROD_REQS)
    if miss:
        return _reject("Production readiness", miss,
            "Add a DTO layer at the API boundary, a @ControllerAdvice "
            "GlobalExceptionHandler, bean-validation annotations (@Valid/@NotNull/...), "
            "and a logging strategy (SLF4J / equivalent).")

    return {"verified": True, "feedback": ""}
