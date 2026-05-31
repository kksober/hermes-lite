"""Tests for multimodal image reading."""
from __future__ import annotations

import base64


def test_read_image_returns_data_uri(tmp_path) -> None:
    from hermes_lite.coding.multimodal import read_image

    # Create a tiny valid PNG
    # Minimal PNG: 8-byte signature + IHDR + IDAT + IEND
    png = tmp_path / "test.png"
    png.write_bytes(_minimal_png())

    result = read_image(str(png))
    assert result["ok"] is True
    assert result["mime_type"] == "image/png"
    assert result["data_uri"].startswith("data:image/png;base64,")
    assert result["size_bytes"] > 0


def test_read_image_not_found(tmp_path) -> None:
    from hermes_lite.coding.multimodal import read_image

    result = read_image(str(tmp_path / "missing.png"))
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_read_image_unsupported_format(tmp_path) -> None:
    from hermes_lite.coding.multimodal import read_image

    txt = tmp_path / "test.txt"
    txt.write_text("hello")

    result = read_image(str(txt))
    assert result["ok"] is False
    assert result["error"] == "unsupported_format"


def test_read_image_supported_models() -> None:
    from hermes_lite.coding.multimodal import read_image_supported

    assert read_image_supported("gpt-4o") is True
    assert read_image_supported("claude-opus-4") is True
    assert read_image_supported("deepseek-v4") is False


def test_read_image_jpeg(tmp_path) -> None:
    from hermes_lite.coding.multimodal import read_image

    # Minimal JPEG
    jpg = tmp_path / "test.jpg"
    jpg.write_bytes(_minimal_jpeg())

    result = read_image(str(jpg))
    assert result["ok"] is True
    assert result["mime_type"] == "image/jpeg"


def test_guess_mime_type() -> None:
    from hermes_lite.coding.multimodal import _guess_mime_type

    assert _guess_mime_type(".png") == "image/png"
    assert _guess_mime_type(".pdf") == "application/pdf"
    assert _guess_mime_type(".webp") == "image/webp"


# ---------------------------------------------------------------------------
# helpers for minimal valid images
# ---------------------------------------------------------------------------


def _minimal_png() -> bytes:
    """Create a minimal valid PNG (1x1 pixel, gray)."""
    import struct, zlib

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    raw = zlib.compress(b"\x00\x80")
    idat = chunk(b"IDAT", raw)
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _minimal_jpeg() -> bytes:
    """Create a tiny valid JPEG (SOI + APP0 + SOF0 + SOS + EOI)."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" \
           b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09" \
           b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f" \
           b"\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342" \
           b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00" \
           b"\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00" \
           b"\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4" \
           b"\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00" \
           b"\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x14" \
           b"\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\x09\x0a\x16\x17" \
           b"\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\xff" \
           b"\xda\x00\x08\x01\x01\x00\x00?\x00\xd2\xcf \xff\xd9"
