"""把來源圖片轉成站上既有的大圖與縮圖。只在同步程序裡執行。"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

from sync.errors import SchemaError

_IMAGE_ID = re.compile(r"^[A-Za-z0-9_-]{6,80}$")


def image_ref(value: object) -> tuple[str, str | None]:
    """回傳 (公開檔名 key, 同步時要抓的路徑或 https 網址)。"""
    if value is None or value == "":
        return "", None
    if not isinstance(value, str):
        raise SchemaError("圖片欄位格式不正確")
    if value.startswith("data:"):
        raise SchemaError("公開投影不接受內嵌圖片")
    if value.startswith("/api/images/"):
        return _api_image(value[len("/api/images/") :]), value.split("?", 1)[0]
    if value.startswith("https://money.klab.tw/api/images/"):
        ident = value.split("/api/images/", 1)[1]
        key = _api_image(ident)
        return key, f"/api/images/{key}"
    if value.startswith("http://"):
        raise SchemaError("圖片只接受 https")
    if value.startswith("https://"):
        parts = urlsplit(value)
        if parts.username or parts.password:
            raise SchemaError("圖片網址含有認證資訊")
        clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        key = "u" + hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]
        return key, clean
    raise SchemaError("圖片欄位格式不正確")


def _api_image(raw: str) -> str:
    ident = raw.split("?", 1)[0].strip("/")
    if not _IMAGE_ID.fullmatch(ident):
        raise SchemaError("圖片 id 格式不正確")
    return ident


def jpeg_variants(raw: bytes) -> tuple[bytes, bytes]:
    """大圖長邊 800、縮圖高 360，對應目前 img/l 與 img/t。"""
    try:
        with Image.open(BytesIO(raw)) as incoming:
            image = incoming.convert("RGB")
    except Exception:
        raise SchemaError("圖片無法解碼") from None
    large = _fit_long_edge(image, 800)
    thumb = _fit_height(image, 360)
    return _encode(large, 80), _encode(thumb, 75)


def _fit_long_edge(image: Image.Image, edge: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= edge:
        return image.copy()
    scale = edge / longest
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )


def _fit_height(image: Image.Image, height_limit: int) -> Image.Image:
    width, height = image.size
    if height <= height_limit:
        return image.copy()
    scale = height_limit / height
    return image.resize((max(1, round(width * scale)), height_limit), Image.Resampling.LANCZOS)


def _encode(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=False)
    return buffer.getvalue()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
