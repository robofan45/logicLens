"""Upload intake: streaming multipart reader, type allow-list, polyglot checks, safe decode, quality.

Zero retention: the upload is read into memory in chunks, decoded with Pillow from a BytesIO,
and dropped when the request ends. Nothing here writes to disk or logs image content.
(Starlette's own form parser spools files larger than 1 MB to a temporary file, which is why the
multipart body is parsed here with python-multipart's streaming parser instead.)
"""
from __future__ import annotations

import io
import math
import struct
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from .errors import ApiError

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PIL_FORMAT = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
ALLOWED_MEDIA_TYPES = tuple(_PIL_FORMAT)

# Markup or archive signatures that make a file a second format as well (a polyglot).
# PDF readers accept '%PDF-' anywhere in the first 1024 bytes; browsers sniff markup in the first 512.
_HEAD_WINDOW = 1024
_MARKUP_SIGNATURES = (b"%pdf-", b"<script", b"<html", b"<svg", b"<?php", b"<!doctype", b"<?xml", b"<body",
                      b"<iframe", b"<object", b"<embed")
_ARCHIVE_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c", b"\x1f\x8b\x08",
                       b"MZ\x90\x00", b"\x7fELF")

UNSUPPORTED = "Only PNG, JPEG and WEBP images are accepted."


def _unsupported(message: str = UNSUPPORTED) -> ApiError:
    return ApiError(415, "E_UNSUPPORTED_MEDIA", message)


def _bad_image(message: str) -> ApiError:
    return ApiError(422, "E_BAD_IMAGE", message)


# ============================================================================ type allow-list
def sniff_media_type(data: bytes) -> Optional[str]:
    """Media type from magic bytes at offset 0; None for anything outside the allow-list."""
    if data.startswith(PNG_MAGIC):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _has_signature(blob: bytes) -> bool:
    low = blob.lower()
    return any(sig in low for sig in _MARKUP_SIGNATURES) or any(sig in blob for sig in _ARCHIVE_SIGNATURES)


def _png_end(data: bytes) -> Optional[int]:
    """Offset just past the IEND chunk, walking chunk lengths (a fake trailing 'IEND' cannot fool it)."""
    pos = len(PNG_MAGIC)
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return None  # truncated: the decoder will reject it
        if kind == b"IEND":
            return end
        pos = end
    return None


def _webp_end(data: bytes) -> Optional[int]:
    (size,) = struct.unpack("<I", data[4:8])
    end = 8 + size + (size & 1)
    return end if end <= len(data) else None


def _jpeg_end(data: bytes) -> Optional[int]:
    """Offset just past EOI, walking marker segments and entropy-coded data."""
    pos, n = 2, len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xD9:
            return pos + 2
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            pos += 2
            continue
        (seg_len,) = struct.unpack(">H", data[pos + 2:pos + 4])
        pos += 2 + seg_len
        if marker == 0xDA:  # start of scan: skip entropy-coded data up to the next real marker
            while pos + 1 < n:
                if data[pos] == 0xFF and data[pos + 1] not in (0x00,) and not (0xD0 <= data[pos + 1] <= 0xD7):
                    break
                pos += 1
    return None


def check_polyglot(data: bytes, media_type: str) -> None:
    """Reject files that are also another format: markup/PDF in the head, or a payload after the image end."""
    if _has_signature(data[:_HEAD_WINDOW]):
        raise _unsupported("File looks like a polyglot (embedded markup or document header); upload a plain image.")
    end = {"image/png": _png_end, "image/webp": _webp_end, "image/jpeg": _jpeg_end}[media_type](data)
    if end is None or end >= len(data):
        return
    trailing = data[end:]
    if media_type == "image/jpeg" and not _has_signature(trailing):
        return  # some cameras append vendor data after EOI; tolerated when it is not another format
    raise _unsupported("File has data after the end of the image (polyglot); upload a plain image.")


def validate_upload(data: bytes) -> str:
    media_type = sniff_media_type(data)
    if media_type is None:
        raise _unsupported()
    check_polyglot(data, media_type)
    return media_type


# ============================================================================ decode
def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if img.mode.startswith("I;16") or img.mode in ("I", "F"):
        arr = np.asarray(img, dtype=np.float64)
        hi = float(arr.max()) if arr.size else 0.0
        scaled = (arr / hi * 255.0) if hi > 255 else arr
        return Image.fromarray(np.clip(scaled, 0, 255).astype(np.uint8), "L").convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def decode_image(data: bytes, media_type: str, *, max_pixels: int, max_side: int) -> Image.Image:
    """Decode with the plugin for the sniffed type only, enforce dimension caps before the pixel
    data is decompressed, apply EXIF orientation and return an RGB image."""
    fmt = _PIL_FORMAT[media_type]
    try:
        img = Image.open(io.BytesIO(data), formats=[fmt])
    except Image.DecompressionBombError:
        raise _bad_image(f"Image dimensions exceed the limit of {max_side} px per side and "
                         f"{max_pixels / 1e6:.0f} MP.") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, struct.error):
        raise _bad_image("The file could not be decoded as an image.") from None
    width, height = img.size
    if width < 1 or height < 1:
        raise _bad_image("The image has no pixels.")
    if width > max_side or height > max_side or width * height > max_pixels:
        raise _bad_image(f"The image is {width}x{height}; the limit is {max_side} px per side and "
                         f"{max_pixels / 1e6:.0f} MP.")
    try:
        img.load()
        img = ImageOps.exif_transpose(img) or img
        return _to_rgb(img)
    except Image.DecompressionBombError:  # pragma: no cover - caught by the explicit cap above
        raise _bad_image("The image is too large.") from None
    except (OSError, ValueError, SyntaxError, struct.error, ZeroDivisionError, MemoryError):
        raise _bad_image("The image is truncated or corrupt.") from None


# ============================================================================ quality
def _clip100(x: float) -> float:
    return float(round(min(100.0, max(0.0, x)), 1))


def quality_metrics(img: Image.Image) -> Dict[str, float]:
    """Blur, contrast and overall, each 0-100 (higher is better).

    Both measures work on D = per-pixel max channel distance from the background (median) colour,
    so coloured ink (RSLogix purple), light and dark themes all score fairly. Contrast is the 99.5th
    percentile of D; blur is the mean of the strongest 0.5% Laplacian responses of D divided by that
    contrast, so it does not drop just because the contrast is low. Calibrated on samples/: the
    RSLogix screenshot scores 100/100, a 2 px Gaussian blur < 10 blur, a 10% contrast copy < 20."""
    width, height = img.size
    small = img
    if max(img.size) > 1024:
        small = img.copy()
        small.thumbnail((1024, 1024), Image.BILINEAR)
    a = np.asarray(small.convert("RGB"), dtype=np.float32)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return {"overall": 0.0, "blur": 0.0, "contrast": 0.0}
    background = np.median(a.reshape(-1, 3), axis=0)
    d = np.abs(a - background).max(axis=2)
    ink = float(np.percentile(d, 99.5))
    contrast = _clip100(ink / 160.0 * 100.0)
    if ink < 8:
        blur = 0.0
    else:
        lap = np.abs(d[1:-1, :-2] + d[1:-1, 2:] + d[:-2, 1:-1] + d[2:, 1:-1] - 4.0 * d[1:-1, 1:-1]).ravel()
        k = max(1, int(lap.size * 0.005))
        top = float(np.partition(lap, -k)[-k:].mean())
        sharpness = top / max(float(np.percentile(d, 99.8)), 8.0)
        blur = _clip100((sharpness - 0.05) / (0.6 - 0.05) * 100.0)
    resolution = min(1.0, min(width, height) / 480.0) * 100.0
    overall = _clip100(0.45 * blur + 0.35 * contrast + 0.20 * resolution)
    if math.isnan(overall):  # pragma: no cover - defensive
        overall = 0.0
    return {"overall": overall, "blur": blur, "contrast": contrast}


# ============================================================================ streaming multipart
@dataclass
class Upload:
    file: bytes
    filename: Optional[str] = None
    fields: Dict[str, str] = field(default_factory=dict)


class MultipartCollector:
    """Incremental multipart/form-data reader. Feed it body chunks as they arrive; it stops with
    413 as soon as the file part or the whole body passes its cap, whatever Content-Length said."""

    MAX_PARTS = 16
    MAX_HEADER_BYTES = 8 * 1024
    TEXT_FIELD_CAP = 256

    def __init__(self, content_type: str, cap_bytes: int, overhead_bytes: int = 64 * 1024,
                 file_field: str = "file", text_fields: Sequence[str] = ("platform",)):
        ctype, params = parse_options_header(content_type or "")
        boundary = params.get(b"boundary")
        if ctype != b"multipart/form-data" or not boundary:
            raise _unsupported("Send the image as multipart/form-data with a 'file' field.")
        if len(boundary) > 200:
            raise ApiError(400, "E_BAD_REQUEST", "Multipart boundary is too long.")
        self.cap = cap_bytes
        self.body_cap = cap_bytes + overhead_bytes
        self.bytes_seen = 0
        self._file_field = file_field.encode()
        self._text_fields = {f.encode() for f in text_fields}
        self._parts = 0
        self._ended = False
        self._header_bytes = 0
        self._hfield = bytearray()
        self._hvalue = bytearray()
        self._headers: Dict[bytes, bytes] = {}
        self._kind: Optional[str] = None  # "file" | "text" | None (ignored part)
        self._name = b""
        self._buf = bytearray()
        self._file: Optional[bytes] = None
        self._filename: Optional[str] = None
        self.fields: Dict[str, str] = {}
        self._parser = MultipartParser(boundary, callbacks={
            "on_part_begin": self._on_part_begin,
            "on_header_field": self._on_header_field,
            "on_header_value": self._on_header_value,
            "on_header_end": self._on_header_end,
            "on_headers_finished": self._on_headers_finished,
            "on_part_data": self._on_part_data,
            "on_part_end": self._on_part_end,
            "on_end": self._on_end,
        })

    # -- public -------------------------------------------------------------------------------
    def too_large(self) -> ApiError:
        mb = self.cap / (1024 * 1024)
        return ApiError(413, "E_TOO_LARGE", f"Upload exceeds the {mb:g} MB limit.")

    def feed(self, chunk: bytes) -> None:
        self.bytes_seen += len(chunk)
        if self.bytes_seen > self.body_cap:
            raise self.too_large()
        try:
            self._parser.write(chunk)
        except MultipartParseError:
            raise ApiError(400, "E_BAD_REQUEST", "Malformed multipart body.") from None

    def finish(self) -> Upload:
        try:
            self._parser.finalize()
        except MultipartParseError:  # pragma: no cover - finalize only checks state
            raise ApiError(400, "E_BAD_REQUEST", "Malformed multipart body.") from None
        if not self._ended:
            raise ApiError(400, "E_BAD_REQUEST", "Malformed multipart body (no closing boundary).")
        if self._file is None:
            raise ApiError(422, "E_VALIDATION", "Missing 'file' field (multipart/form-data).",
                           details=[{"loc": ["file"], "msg": "Field required", "type": "missing"}])
        return Upload(self._file, self._filename, dict(self.fields))

    # -- callbacks ------------------------------------------------------------------------------
    def _on_part_begin(self) -> None:
        self._parts += 1
        if self._parts > self.MAX_PARTS:
            raise ApiError(422, "E_VALIDATION", "Too many form fields.")
        self._headers = {}
        self._header_bytes = 0
        self._kind = None
        self._buf = bytearray()

    def _count_header(self, n: int) -> None:
        self._header_bytes += n
        if self._header_bytes > self.MAX_HEADER_BYTES:
            raise ApiError(400, "E_BAD_REQUEST", "Multipart part headers are too large.")

    def _on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._count_header(end - start)
        self._hfield += data[start:end]

    def _on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._count_header(end - start)
        self._hvalue += data[start:end]

    def _on_header_end(self) -> None:
        self._headers[bytes(self._hfield).strip().lower()] = bytes(self._hvalue).strip()
        self._hfield = bytearray()
        self._hvalue = bytearray()

    def _on_headers_finished(self) -> None:
        _, params = parse_options_header(self._headers.get(b"content-disposition", b"").decode("latin-1"))
        self._name = params.get(b"name", b"")
        if self._name == self._file_field:
            if self._file is not None:
                raise ApiError(422, "E_VALIDATION", "Send exactly one 'file'.")
            self._kind = "file"
            fname = params.get(b"filename")
            self._filename = fname.decode("utf-8", "replace")[:255] if fname else None
        elif self._name in self._text_fields:
            self._kind = "text"

    def _on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._kind is None:
            return
        n = end - start
        if self._kind == "file" and len(self._buf) + n > self.cap:
            raise self.too_large()
        if self._kind == "text" and len(self._buf) + n > self.TEXT_FIELD_CAP:
            raise ApiError(422, "E_VALIDATION", f"Form field '{self._name.decode('latin-1')}' is too long.")
        self._buf += data[start:end]

    def _on_part_end(self) -> None:
        if self._kind == "file":
            self._file = bytes(self._buf)
        elif self._kind == "text":
            try:
                self.fields[self._name.decode("latin-1")] = self._buf.decode("utf-8").strip()
            except UnicodeDecodeError:
                raise ApiError(422, "E_VALIDATION", "Form fields must be UTF-8 text.") from None
        self._buf = bytearray()
        self._kind = None

    def _on_end(self) -> None:
        self._ended = True
