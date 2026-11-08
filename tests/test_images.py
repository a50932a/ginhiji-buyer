"""圖片縮放測試。不讀取正式商品圖。"""

from io import BytesIO

from PIL import Image

from sync.images import jpeg_variants


def test_variants_are_deterministic_and_within_the_existing_sizes():
    buffer = BytesIO()
    Image.new("RGB", (1200, 600), "navy").save(buffer, format="JPEG")
    raw = buffer.getvalue()
    first = jpeg_variants(raw)
    second = jpeg_variants(raw)
    assert first == second
    large = Image.open(BytesIO(first[0]))
    thumb = Image.open(BytesIO(first[1]))
    assert max(large.size) == 800
    assert thumb.size[1] == 360
