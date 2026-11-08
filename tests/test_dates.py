"""日期解析。失敗那次的日誌沒有原始日期，只出現「日期格式無法辨識」。

舊解析器只接受開頭為 YYYY-MM-DD 的字串，所以 ISO 會過、JavaScript Date.toString() 會被拒。
這裡涵蓋文件上的日期、帶時區的 ISO，以及實際 Node 在台北時區的 toString 形狀。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sync.errors import SchemaError
from sync.money import public_date
from sync.project import project_publication
from sync.sync_orders import run_sync
from tests.test_project import base_group, flat, item
from tests.test_sync_run import GROUP_A, FakeSource, bundle, site_root

JS_TAIPEI = "Sun Nov 08 2026 20:08:12 GMT+0800 (Taiwan Standard Time)"


def test_date_only_stays_on_that_calendar_day():
    assert public_date("2026-11-08", "startedAt") == "2026-11-08"
    assert public_date(" 2026-11-08 ", "startedAt") == "2026-11-08"


def test_iso_offsets_convert_to_taipei():
    assert public_date("2026-11-07T16:30:00.000Z", "paidAt") == "2026-11-08"
    assert public_date("2026-11-08T01:02:03Z", "paidAt") == "2026-11-08"
    assert public_date("2026-11-08T20:08:12+08:00", "paidAt") == "2026-11-08"
    assert public_date("2026-11-08T20:08:12+0800", "paidAt") == "2026-11-08"
    assert public_date("2026-11-08T00:30:00+09:00", "paidAt") == "2026-11-07"
    assert public_date("2026-11-08 00:30:00", "paidAt") == "2026-11-08"


def test_javascript_tostring_uses_its_offset_then_taipei():
    assert public_date(JS_TAIPEI, "paidAt") == "2026-11-08"
    utc = "Sun Nov 08 2026 20:30:00 GMT+0000 (Coordinated Universal Time)"
    assert public_date(utc, "paidAt") == "2026-11-09"


def test_empty_dates_are_blank_and_malformed_dates_hide_the_value():
    assert public_date(None, "paidAt") == ""
    assert public_date("", "startedAt") == ""
    samples = [
        "not-a-date",
        "2026-13-01",
        "Sun Nov 99 2026 20:08:00 GMT+0800 (Taiwan Standard Time)",
        "2026/11/08",
    ]
    for sample in samples:
        with pytest.raises(SchemaError, match=r"^日期格式無法辨識（paidAt）$") as caught:
            public_date(sample, "paidAt")
        assert sample not in str(caught.value)
    with pytest.raises(SchemaError, match=r"^日期格式無法辨識（startedAt）$"):
        public_date(123456, "startedAt")


def test_projection_accepts_javascript_started_at_and_iso_payment():
    group_id = "a" * 32
    detail = {
        "groupBuy": base_group(group_id),
        "orders": [
            {
                "id": "order-1",
                "buyerName": "買家甲",
                "isSelf": False,
                "items": [item("item-1", "測試品", "100", "")],
                "payments": [{"amount": "10", "paidAt": JS_TAIPEI, "note": "測試"}],
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": "order-1",
                    "goodsCharge": "23",
                    "feeCharge": "0",
                    "charge": "23",
                    "paidSum": "10",
                    "remaining": "13",
                }
            ]
        },
    }
    detail["groupBuy"]["startedAt"] = "2026-11-08"
    public, _images = project_publication(
        [detail],
        {group_id: [flat("item-1", group_id, "測試品", "100", "")]},
        [{"name": "買家甲", "charge": "23", "paidSum": "10", "remaining": "13"}],
        previous=None,
        billing_ids=[],
        fetched_at="2026-11-08 21:00",
        empty_text="沒有",
    )
    assert public["gbs"][0]["dt"] == "2026-11-08"
    assert public["gbs"][0]["o"][0]["pay"][0][1] == "2026-11-08"


def test_malformed_date_does_not_replace_public_data(tmp_path: Path):
    groups, items, buyers = bundle()
    groups[GROUP_A]["orders"][0]["payments"] = [
        {"amount": "1", "paidAt": "not-a-date", "note": "不應出現在錯誤"}
    ]
    source = FakeSource(groups, items, buyers)
    root = site_root(tmp_path, [GROUP_A])
    previous = root / "data" / "public.json"
    assert run_sync(root, FakeSource(*bundle()), dry_run=False) == "updated"
    before = previous.read_bytes()
    with pytest.raises(SchemaError, match=r"^日期格式無法辨識（paidAt）$") as caught:
        run_sync(root, source, dry_run=False)
    assert previous.read_bytes() == before
    assert "not-a-date" not in str(caught.value)
    assert "不應出現在錯誤" not in str(caught.value)
