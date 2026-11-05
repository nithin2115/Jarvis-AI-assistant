"""
JARVIS Auth — Google OAuth (authlib)
Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env
"""
import os, logging
from authlib.integrations.flask_client import OAuth

logger = logging.getLogger("jarvis.oauth")
oauth  = OAuth()
_ready = False


def init_oauth(app) -> bool:
    global _ready
    cid = os.getenv("GOOGLE_CLIENT_ID",     "")
    csc = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not cid or not csc:
        logger.warning("[OAUTH] GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set")
        return False
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=cid,
        client_secret=csc,
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile"},
    )
    _ready = True
    logger.info("[OAUTH] Google OAuth ready")
    return True


def is_ready() -> bool:
    return _ready


def get_google():
    return oauth.google
