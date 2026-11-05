"""
JARVIS File Processor — text + image extraction for chat uploads.

Supports:
  • Images (jpg/png/gif/webp/bmp) → kept as bytes for Gemini Vision.
  • PDFs                          → text extracted via PyPDF2.
  • Code / text / markdown        → read directly.
  • DOCX                          → text extracted via python-docx.
  • ZIP                           → list contents + extract text members.

Returns a uniform dict per file:
    {
      "id": <str>,                # unique upload id
      "name": <str>,
      "kind": "image" | "pdf" | "code" | "text" | "doc" | "zip" | "data" | "unknown",
      "size": <int>,
      "mime": <str>,
      "text": <str>,              # extracted text (may be empty for images)
      "image": {                  # only if kind == "image"
          "mime_type": "image/png",
          "data": <bytes>         # raw image bytes (for Gemini Vision)
      }
    }
"""
from __future__ import annotations

import io
import os
import re
import uuid
import zipfile
import logging
import mimetypes
from typing import Optional, Tuple, List, Dict
from pathlib import Path

logger = logging.getLogger("jarvis.uploads")

# ── Limits (defensive: keep RAM low) ────────────────────────────────────────
MAX_FILE_BYTES        = 25 * 1024 * 1024     # 25 MB per file
MAX_TEXT_CHARS        = 60_000               # truncate per file in context
MAX_ZIP_MEMBERS       = 30
MAX_ZIP_MEMBER_BYTES  = 2 * 1024 * 1024      # 2 MB per zip member
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".c", ".cc", ".cpp",
    ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".m", ".mm",
    ".sql", ".sh", ".bat", ".ps1", ".html", ".css", ".scss", ".less",
    ".xml", ".json", ".yaml", ".yml", ".toml", ".ini", ".env",
    ".csv", ".tsv",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _safe_decode(b: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _truncate(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n…[truncated {len(text)-limit} chars]"


def _extract_pdf(data: bytes) -> str:
    try:
        from PyPDF2 import PdfReader
    except Exception:
        try:
            from pypdf import PdfReader  # fallback
        except Exception as e:
            logger.warning(f"[UPLOAD] PDF reader unavailable: {e}")
            return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        chunks = []
        for page in reader.pages[:80]:  # cap pages defensively
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(c.strip() for c in chunks if c).strip()
    except Exception as e:
        logger.warning(f"[UPLOAD] PDF extract failed: {e}")
        return ""


def _extract_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except Exception as e:
        logger.warning(f"[UPLOAD] python-docx unavailable: {e}")
        return ""
    try:
        doc = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text).strip()
    except Exception as e:
        logger.warning(f"[UPLOAD] DOCX extract failed: {e}")
        return ""


def _extract_zip(name: str, data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()[:MAX_ZIP_MEMBERS]
            head = [f"ZIP archive '{name}' contains {len(zf.namelist())} entries (showing {len(names)}):"]
            for n in names:
                head.append(f"  - {n}")
            chunks = ["\n".join(head)]
            for n in names:
                ext = os.path.splitext(n)[1].lower()
                if ext not in TEXT_EXTS:
                    continue
                try:
                    info = zf.getinfo(n)
                    if info.file_size > MAX_ZIP_MEMBER_BYTES:
                        continue
                    with zf.open(n) as f:
                        body = _safe_decode(f.read(MAX_ZIP_MEMBER_BYTES))
                    if body.strip():
                        chunks.append(f"\n----- {n} -----\n{_truncate(body, 8000)}")
                except Exception:
                    continue
            return "\n".join(chunks).strip()
    except Exception as e:
        logger.warning(f"[UPLOAD] ZIP read failed: {e}")
        return f"(Could not read ZIP '{name}': {e})"


def _classify(name: str, mime: str) -> Tuple[str, str]:
    ext = os.path.splitext(name)[1].lower()
    mime = (mime or "").lower()
    if ext in IMAGE_EXTS or mime.startswith("image/"):
        return "image", mime or mimetypes.guess_type(name)[0] or "image/png"
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf", "application/pdf"
    if ext == ".docx":
        return "doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".zip" or mime == "application/zip":
        return "zip", "application/zip"
    if ext in {".csv", ".tsv"}:
        return "data", mime or "text/csv"
    if ext in TEXT_EXTS or mime.startswith("text/"):
        # Distinguish code vs plain text only by extension — useful for syntax hint
        code_exts = {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".c", ".cc",
            ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sql",
            ".sh", ".bat", ".ps1", ".html", ".css", ".scss", ".less",
            ".xml", ".json", ".yaml", ".yml", ".toml", ".ini",
        }
        return ("code" if ext in code_exts else "text"), (mime or "text/plain")
    return "unknown", mime or "application/octet-stream"


def process_upload(filename: str, raw: bytes,
                   mime: Optional[str] = None) -> Optional[Dict]:
    """Process a single uploaded file. Returns the descriptor dict or None."""
    if not filename:
        return None
    if raw is None:
        return None
    if len(raw) > MAX_FILE_BYTES:
        logger.warning(f"[UPLOAD] {filename} too large ({len(raw)} bytes); rejected")
        return {
            "id": str(uuid.uuid4()),
            "name": filename,
            "kind": "unknown",
            "size": len(raw),
            "mime": mime or "application/octet-stream",
            "text": f"(File '{filename}' rejected: exceeds {MAX_FILE_BYTES // (1024*1024)} MB limit.)",
            "rejected": True,
        }

    safe_name = os.path.basename(filename)[:200]
    kind, mime_resolved = _classify(safe_name, mime or "")

    desc: Dict = {
        "id": str(uuid.uuid4()),
        "name": safe_name,
        "kind": kind,
        "size": len(raw),
        "mime": mime_resolved,
        "text": "",
    }

    try:
        if kind == "image":
            desc["image"] = {"mime_type": mime_resolved, "data": raw}
            desc["text"] = f"(Image attached: {safe_name})"
        elif kind == "pdf":
            desc["text"] = _truncate(_extract_pdf(raw))
        elif kind == "doc":
            desc["text"] = _truncate(_extract_docx(raw))
        elif kind == "zip":
            desc["text"] = _truncate(_extract_zip(safe_name, raw))
        elif kind in ("code", "text", "data"):
            desc["text"] = _truncate(_safe_decode(raw))
        else:
            # Last-ditch: try as text
            desc["text"] = _truncate(_safe_decode(raw))
            if not desc["text"].strip():
                desc["text"] = f"(Binary file '{safe_name}' — no extractable text.)"
    except Exception as e:
        logger.warning(f"[UPLOAD] Extract failed for {safe_name}: {e}")
        desc["text"] = f"(Could not extract content from '{safe_name}': {e})"

    return desc


def build_attachment_context(attachments: List[Dict],
                             max_total_chars: int = 80_000) -> str:
    """Compose a text block describing attachments for the LLM context window."""
    if not attachments:
        return ""
    lines: List[str] = ["=== USER ATTACHMENTS ==="]
    used = 0
    for a in attachments:
        kind  = a.get("kind", "unknown")
        name  = a.get("name", "file")
        size  = a.get("size", 0)
        text  = a.get("text", "") or ""
        head  = f"\n--- {name} ({kind}, {size} bytes) ---"
        budget = max(0, max_total_chars - used - len(head))
        if budget <= 0:
            lines.append(f"\n--- {name} ({kind}) [omitted: context full] ---")
            break
        snippet = text if len(text) <= budget else text[:budget].rstrip() + " …[truncated]"
        lines.append(head)
        lines.append(snippet)
        used += len(head) + len(snippet)
    lines.append("\n=== END ATTACHMENTS ===")
    return "\n".join(lines)


def collect_images(attachments: List[Dict]) -> List[Dict]:
    """Return image dicts ready for Gemini Vision: [{mime_type, data}]."""
    out = []
    for a in attachments:
        if a.get("kind") == "image" and a.get("image"):
            out.append(a["image"])
    return out


# ── Optional in-memory store (per-session) ──────────────────────────────────
# Uses a simple dict; entries can be evicted by LRU caller. Stored bytes
# are kept ONLY for images so we can pass them to Gemini Vision later.
_STORE: Dict[str, Dict] = {}
_STORE_ORDER: List[str] = []
_STORE_MAX = 32  # total active uploads across all sessions


def remember(desc: Dict) -> str:
    """Store an upload descriptor and return its id."""
    fid = desc["id"]
    _STORE[fid] = desc
    _STORE_ORDER.append(fid)
    while len(_STORE_ORDER) > _STORE_MAX:
        old = _STORE_ORDER.pop(0)
        _STORE.pop(old, None)
    return fid


def fetch(ids: List[str]) -> List[Dict]:
    """Fetch upload descriptors by id, in order; missing ids are skipped."""
    out = []
    for i in ids or []:
        d = _STORE.get(i)
        if d:
            out.append(d)
    return out


def forget(fid: str) -> bool:
    if fid in _STORE:
        _STORE.pop(fid, None)
        try:
            _STORE_ORDER.remove(fid)
        except ValueError:
            pass
        return True
    return False
