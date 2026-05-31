"""Multimodal input: read image/PDF files for vision-capable models.

Detects model capabilities and returns either structured metadata for
the caller to embed, or a graceful fallback for non-vision models.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_PDF_EXTENSION = ".pdf"
_READABLE_EXTENSIONS = _IMAGE_EXTENSIONS | {_PDF_EXTENSION}


def _guess_mime_type(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".pdf": "application/pdf",
    }.get(suffix.lower(), "application/octet-stream")


def read_image(path: str) -> dict[str, object]:
    """Read an image or PDF file and return a base64 data-URI.

    For vision-capable models the returned ``data_uri`` can be injected
    into the prompt.  Callers should check ``model_supports_vision``
    before passing the URI to the model.
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "not_found", "path": path}

    suffix = p.suffix.lower()
    if suffix not in _READABLE_EXTENSIONS:
        return {
            "ok": False,
            "error": "unsupported_format",
            "path": path,
            "hint": f"Supported: {', '.join(sorted(_READABLE_EXTENSIONS))}",
        }

    try:
        data = p.read_bytes()
    except Exception as exc:
        return {"ok": False, "error": "read_failed", "detail": str(exc)}

    mime = _guess_mime_type(suffix)
    b64 = base64.b64encode(data).decode("ascii")
    data_uri = f"data:{mime};base64,{b64}"

    return {
        "ok": True,
        "path": str(p.resolve()),
        "mime_type": mime,
        "size_bytes": len(data),
        "data_uri": data_uri,
        "data_uri_length": len(data_uri),
    }


def read_image_supported(model_name: str) -> bool:
    """Check if the model name suggests vision/multimodal support."""
    vision_keywords = [
        "gpt-4o", "gpt-4-turbo", "gpt-4-vision",
        "claude", "gemini",
        "vision", "multimodal", "vl",
        "pixtral", "llava", "cogvlm",
    ]
    lower = model_name.lower()
    return any(kw in lower for kw in vision_keywords)
