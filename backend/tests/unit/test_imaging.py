import io
import struct
import zlib

import pytest
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from app.errors import ApiError
from app.imaging import (
    MultipartCollector, decode_image, quality_metrics, sniff_media_type, validate_upload,
)
from tests.helpers import SAMPLE_IMAGE, encode, png_bytes


# ------------------------------------------------------------------ magic bytes / polyglots
def _webp() -> bytes:
    return encode(Image.new("RGB", (32, 16), "white"), "WEBP")


def _jpeg() -> bytes:
    return encode(Image.new("RGB", (32, 16), "white"), "JPEG", quality=90)


@pytest.mark.parametrize("data,expected", [
    (png_bytes(), "image/png"),
    (_jpeg(), "image/jpeg"),
    (_webp(), "image/webp"),
])
def test_allowed_types_are_sniffed_from_magic_bytes(data, expected):
    assert sniff_media_type(data) == expected
    assert validate_upload(data) == expected


@pytest.mark.parametrize("name,data", [
    ("gif", encode(Image.new("RGB", (8, 8)), "GIF")),
    ("svg", b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ("svg-no-decl", b"<svg onload=alert(1)></svg>"),
    ("pdf", b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"),
    ("html", b"<!doctype html><html><script>alert(1)</script></html>"),
    ("bmp", encode(Image.new("RGB", (8, 8)), "BMP")),
    ("tiff", encode(Image.new("RGB", (8, 8)), "TIFF")),
    ("zip", b"PK\x03\x04" + b"\x00" * 40),
    ("riff-not-webp", b"RIFF\x10\x00\x00\x00WAVEfmt " + b"\x00" * 16),
    ("empty", b""),
    ("tiny", b"\x89P"),
])
def test_everything_else_is_415(name, data):
    assert sniff_media_type(data) is None
    with pytest.raises(ApiError) as exc:
        validate_upload(data)
    assert (exc.value.status, exc.value.code) == (415, "E_UNSUPPORTED_MEDIA")


def test_png_with_appended_zip_is_rejected_as_polyglot():
    data = png_bytes() + b"PK\x03\x04" + b"payload" * 10
    with pytest.raises(ApiError) as exc:
        validate_upload(data)
    assert exc.value.code == "E_UNSUPPORTED_MEDIA"
    assert "polyglot" in exc.value.message


def test_png_with_any_trailing_bytes_after_iend_is_rejected():
    with pytest.raises(ApiError):
        validate_upload(png_bytes() + b"\x00")


def test_jpeg_with_pdf_header_in_first_kilobyte_is_rejected():
    # A COM segment carrying '%PDF-' makes the file a JPEG/PDF polyglot (PDF readers scan 1 KB).
    jpeg = _jpeg()
    comment = b"%PDF-1.4 hidden"
    seg = b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment
    data = jpeg[:2] + seg + jpeg[2:]
    Image.open(io.BytesIO(data)).load()  # still a valid JPEG
    with pytest.raises(ApiError) as exc:
        validate_upload(data)
    assert exc.value.code == "E_UNSUPPORTED_MEDIA"


def test_jpeg_with_html_after_eoi_is_rejected_but_plain_trailing_junk_is_tolerated():
    jpeg = _jpeg()
    with pytest.raises(ApiError):
        validate_upload(jpeg + b"<html><script>alert(1)</script></html>")
    # Some cameras append vendor data after EOI; harmless bytes are accepted.
    assert validate_upload(jpeg + b"\x00\x01vendor-data") == "image/jpeg"


def test_webp_with_bytes_beyond_riff_size_is_rejected():
    with pytest.raises(ApiError):
        validate_upload(_webp() + b"<script>")


# ------------------------------------------------------------------ decode limits
def _limits(**kw):
    base = {"max_pixels": 40_000_000, "max_side": 8000}
    base.update(kw)
    return base


def test_decode_valid_png_returns_rgb():
    img = decode_image(png_bytes(80, 40), "image/png", **_limits())
    assert img.mode == "RGB" and img.size == (80, 40)


def test_truncated_file_is_422_bad_image():
    data = encode(Image.effect_noise((256, 256), 64).convert("RGB"), "PNG")
    truncated = data[: len(data) // 2]
    with pytest.raises(ApiError) as exc:
        decode_image(truncated, "image/png", **_limits())
    assert (exc.value.status, exc.value.code) == (422, "E_BAD_IMAGE")


def _png_header_only(width: int, height: int) -> bytes:
    """A tiny PNG whose IHDR claims huge dimensions (classic decompression-bomb probe)."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 64)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.mark.parametrize("w,h", [(9000, 100), (100, 9000), (7000, 7000), (100_000, 100_000)])
def test_huge_dimensions_are_rejected_before_decoding(w, h):
    with pytest.raises(ApiError) as exc:
        decode_image(_png_header_only(w, h), "image/png", **_limits())
    assert exc.value.code == "E_BAD_IMAGE"
    assert "limit" in exc.value.message


def test_real_decompression_bomb_is_rejected():
    # 6000 x 6000 of zeros compresses to a few KB but would decode to 108 MB of RGB.
    img = Image.new("L", (6000, 6000), 0)
    data = encode(img, "PNG", optimize=True)
    assert len(data) < 200_000
    with pytest.raises(ApiError) as exc:
        decode_image(data, "image/png", **_limits(max_pixels=20_000_000))
    assert exc.value.code == "E_BAD_IMAGE"


def test_format_must_match_sniffed_type():
    # JPEG bytes claimed as PNG must not be decoded by another plugin.
    with pytest.raises(ApiError) as exc:
        decode_image(_jpeg(), "image/png", **_limits())
    assert exc.value.code == "E_BAD_IMAGE"


def test_exif_orientation_is_applied():
    img = Image.new("RGB", (60, 20), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    data = encode(img, "JPEG", exif=exif.tobytes())
    out = decode_image(data, "image/jpeg", **_limits())
    assert out.size == (20, 60)


def test_transparent_png_is_composited_on_white():
    rgba = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    out = decode_image(encode(rgba, "PNG"), "image/png", **_limits())
    assert out.mode == "RGB" and out.getpixel((5, 5)) == (255, 255, 255)


@pytest.mark.parametrize("mode", ["L", "P", "LA", "I;16", "CMYK"])
def test_other_modes_convert_to_rgb(mode):
    img = Image.new(mode, (12, 12))
    fmt = "JPEG" if mode == "CMYK" else "PNG"
    media = "image/jpeg" if fmt == "JPEG" else "image/png"
    out = decode_image(encode(img, fmt), media, **_limits())
    assert out.mode == "RGB"


# ------------------------------------------------------------------ quality metrics
def test_quality_scores_are_0_to_100_and_rank_sharp_above_blurred():
    img = Image.open(SAMPLE_IMAGE).convert("RGB")
    sharp = quality_metrics(img)
    blurred = quality_metrics(img.filter(ImageFilter.GaussianBlur(2)))
    flat = quality_metrics(ImageEnhance.Contrast(img).enhance(0.1))
    for q in (sharp, blurred, flat):
        assert set(q) == {"overall", "blur", "contrast"}
        assert all(0 <= v <= 100 for v in q.values())
    assert sharp["blur"] >= 80
    assert blurred["blur"] < 30
    assert sharp["contrast"] >= 80
    assert flat["contrast"] < 30
    assert sharp["overall"] > blurred["overall"] and sharp["overall"] > flat["overall"]


def test_quality_of_blank_image_is_low_not_an_error():
    q = quality_metrics(Image.new("RGB", (100, 100), "white"))
    assert q["contrast"] == 0 and q["overall"] < 40


def test_quality_handles_dark_mode_screenshots():
    img = Image.new("RGB", (300, 200), (20, 20, 20))
    d = ImageDraw.Draw(img)
    for y in range(20, 200, 40):
        d.line([(10, y), (290, y)], fill=(230, 230, 230), width=2)
    assert quality_metrics(img)["contrast"] >= 80


# ------------------------------------------------------------------ streaming multipart
def _multipart(parts, boundary="XyZbOuNdArY"):
    out = b""
    for name, value, filename, ctype in parts:
        out += f"--{boundary}\r\n".encode()
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        out += f"Content-Disposition: {disp}\r\n".encode()
        if ctype:
            out += f"Content-Type: {ctype}\r\n".encode()
        out += b"\r\n" + value + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", out


def _feed(collector, body, chunk=1000):
    for i in range(0, len(body), chunk):
        collector.feed(body[i:i + chunk])
    return collector.finish()


def test_multipart_collects_file_and_platform_in_memory():
    ctype, body = _multipart([("platform", b"rockwell_slc", None, None),
                              ("file", png_bytes(), "a.png", "image/png")])
    upload = _feed(MultipartCollector(ctype, cap_bytes=1_000_000), body, chunk=7)
    assert upload.file == png_bytes()
    assert upload.fields == {"platform": "rockwell_slc"}


def test_multipart_stops_streaming_at_the_cap_without_content_length():
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * 300_000
    ctype, body = _multipart([("file", big, "big.png", "image/png")])
    collector = MultipartCollector(ctype, cap_bytes=100_000)
    with pytest.raises(ApiError) as exc:
        _feed(collector, body, chunk=4096)
    assert (exc.value.status, exc.value.code) == (413, "E_TOO_LARGE")
    assert collector.bytes_seen < 200_000  # stopped early, did not read everything


def test_multipart_total_body_cap_counts_every_part():
    ctype, body = _multipart([(f"junk{i}", b"x" * 200, None, None) for i in range(6)]
                             + [("file", png_bytes(), "a.png", None)])
    with pytest.raises(ApiError) as exc:
        _feed(MultipartCollector(ctype, cap_bytes=600, overhead_bytes=200), body)
    assert exc.value.status == 413


def test_multipart_missing_file_is_422():
    ctype, body = _multipart([("platform", b"unknown", None, None)])
    with pytest.raises(ApiError) as exc:
        _feed(MultipartCollector(ctype, cap_bytes=10_000), body)
    assert (exc.value.status, exc.value.code) == (422, "E_VALIDATION")


def test_multipart_two_files_is_422():
    ctype, body = _multipart([("file", png_bytes(), "a.png", None), ("file", png_bytes(), "b.png", None)])
    with pytest.raises(ApiError) as exc:
        _feed(MultipartCollector(ctype, cap_bytes=100_000), body)
    assert exc.value.code == "E_VALIDATION"


def test_multipart_oversized_text_field_is_rejected():
    ctype, body = _multipart([("platform", b"p" * 5000, None, None), ("file", png_bytes(), "a.png", None)])
    with pytest.raises(ApiError) as exc:
        _feed(MultipartCollector(ctype, cap_bytes=100_000), body)
    assert exc.value.status in (413, 422)


def test_multipart_too_many_parts_is_rejected():
    ctype, body = _multipart([(f"f{i}", b"1", None, None) for i in range(40)] + [("file", png_bytes(), "a", None)])
    with pytest.raises(ApiError) as exc:
        _feed(MultipartCollector(ctype, cap_bytes=100_000), body)
    assert exc.value.code == "E_VALIDATION"


@pytest.mark.parametrize("ctype", ["application/json", "multipart/form-data", "text/plain; boundary=x", ""])
def test_non_multipart_or_missing_boundary_is_415(ctype):
    with pytest.raises(ApiError) as exc:
        MultipartCollector(ctype, cap_bytes=100)
    assert exc.value.code == "E_UNSUPPORTED_MEDIA"


def test_truncated_multipart_body_is_400():
    ctype, body = _multipart([("file", png_bytes(), "a.png", None)])
    with pytest.raises(ApiError) as exc:
        _feed(MultipartCollector(ctype, cap_bytes=100_000), body[:-30])
    assert (exc.value.status, exc.value.code) == (400, "E_BAD_REQUEST")
