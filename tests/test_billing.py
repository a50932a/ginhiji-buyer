"""請款預告支援限定買家，純 id 條目維持原本行為。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sync.errors import SchemaError
from sync.project import parse_billing_include, project_publication
from sync.sync_orders import load_billing_file, run_sync
from tests.test_project import base_group, flat, item
from tests.test_sync_run import FakeSource, site_root


GROUP_FILTER = "1" * 32
GROUP_PLAIN = "2" * 32


def test_parse_billing_include_keeps_plain_ids_and_reads_buyer_lists():
    plain = "a" * 32
    filtered = "b" * 32
    entries = parse_billing_include(
        [plain, {"id": filtered, "buyers": ["Kris", "Mita"]}],
        allow_empty=False,
    )
    assert [(entry.id, entry.buyers) for entry in entries] == [
        (plain, None),
        (filtered, ("Kris", "Mita")),
    ]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"id": "c" * 32, "buyers": []}, "買家清單不正確"),
        ({"id": "c" * 32, "buyers": ["Kris", "Kris"]}, "重複的買家"),
        ({"id": "c" * 32, "buyers": [" Kris"]}, "買家名稱不正確"),
        ({"id": "c" * 32, "exclude": ["小芳"]}, "不支援的欄位"),
        ({"id": "not-an-id", "buyers": ["Kris"]}, "不正確的 id"),
        (["a" * 32, "a" * 32], "重複 id"),
        (123, "格式不正確"),
    ],
)
def test_parse_billing_include_rejects_invalid_entries(raw, message):
    payload = raw if isinstance(raw, list) else [raw]
    with pytest.raises(SchemaError, match=message):
        parse_billing_include(payload, allow_empty=False)


def test_load_billing_file_rejects_empty_include(tmp_path: Path):
    path = tmp_path / "billing_groups.json"
    path.write_text(json.dumps({"include": [], "empty": "沒有"}), encoding="utf-8")
    with pytest.raises(SchemaError, match="沒有 id"):
        load_billing_file(path)


def test_billing_buyer_list_includes_only_named_unpaid_buyers():
    details, items, summary = _gin_group_bundle()
    public, _images = project_publication(
        details,
        items,
        summary,
        previous=None,
        billing_ids=[
            {"id": GROUP_FILTER, "buyers": ["Kris", "Mita"]},
            GROUP_PLAIN,
        ],
        fetched_at="2026-11-14 14:00",
        empty_text="月中暫無款項請款",
    )
    filtered_name = details[0]["groupBuy"]["name"]
    plain_name = details[1]["groupBuy"]["name"]
    by_group = {row["name"]: row for row in public["billing"]["items"]}
    assert by_group[filtered_name]["amount"] == 1208
    assert by_group[filtered_name]["note"] == "人民幣 ¥276"
    assert by_group[plain_name]["amount"] == 100
    buyers = {row["name"]: row for row in public["billing"]["buyers"]}
    assert buyers["Kris"]["total"] == 704
    assert buyers["Kris"]["items"] == [
        {"name": filtered_name, "amount": 604, "note": ""},
        {"name": plain_name, "amount": 100, "note": ""},
    ]
    assert buyers["Mita"]["total"] == 604
    assert buyers["Mita"]["items"] == [{"name": filtered_name, "amount": 604, "note": ""}]
    assert "小芳" not in buyers
    assert "小衛" not in buyers
    assert "白米" not in buyers
    assert "阿蝶" not in buyers
    encoded = json.dumps(public, ensure_ascii=False)
    for secret in ("costRate", "profit", "payouts", "email"):
        assert secret not in encoded


def test_billing_plain_id_still_includes_every_unpaid_non_self_buyer():
    details, items, summary = _gin_group_bundle()
    public, _images = project_publication(
        details,
        items,
        summary,
        previous=None,
        billing_ids=[GROUP_FILTER],
        fetched_at="2026-11-14 14:00",
        empty_text="月中暫無款項請款",
    )
    name = details[0]["groupBuy"]["name"]
    assert public["billing"]["items"][0]["amount"] == 1208 + 306 + 604
    buyers = {row["name"] for row in public["billing"]["buyers"]}
    assert buyers == {"Kris", "Mita", "小芳", "小衛"}
    amounts = {
        row["name"]: next(item["amount"] for item in row["items"] if item["name"] == name)
        for row in public["billing"]["buyers"]
        if any(item["name"] == name for item in row["items"])
    }
    assert amounts == {"Kris": 604, "Mita": 604, "小芳": 306, "小衛": 604}


def test_billing_missing_named_buyer_aborts():
    details, items, summary = _gin_group_bundle()
    with pytest.raises(SchemaError, match="指定的買家不在團內"):
        project_publication(
            details,
            items,
            summary,
            previous=None,
            billing_ids=[{"id": GROUP_FILTER, "buyers": ["Kris", "不存在的人"]}],
            fetched_at="2026-11-14 14:00",
            empty_text="月中暫無款項請款",
        )


def test_sync_accepts_buyer_list_entries(tmp_path: Path):
    from tests.test_sync_run import GROUP_A, GROUP_B, bundle, detail_for

    groups, items, buyers = bundle()
    groups[GROUP_A] = detail_for(GROUP_A, "Kris", "11")
    groups[GROUP_A]["orders"].append(
        {
            "id": f"{GROUP_A[:8]}-other",
            "buyerName": "小芳",
            "isSelf": False,
            "items": [item(f"{GROUP_A[:8]}-other", "測試品", "100", "")],
            "payments": [],
        }
    )
    groups[GROUP_A]["settlement"]["orders"].append(
        {
            "orderId": f"{GROUP_A[:8]}-other",
            "goodsCharge": "22",
            "feeCharge": "0",
            "charge": "22",
            "paidSum": "0",
            "remaining": "22",
        }
    )
    items[GROUP_A].append(flat(f"{GROUP_A[:8]}-other", GROUP_A, "測試品", "100", ""))
    buyers = [
        {"name": "Kris", "charge": "11", "paidSum": "0", "remaining": "11"},
        {"name": "小芳", "charge": "22", "paidSum": "0", "remaining": "22"},
        {"name": "買家乙", "charge": "22", "paidSum": "0", "remaining": "22"},
    ]
    source = FakeSource(groups, items, buyers)
    root = site_root(tmp_path, [GROUP_A, GROUP_B])
    (root / "sync" / "billing_groups.json").write_text(
        json.dumps(
            {
                "include": [
                    {"id": GROUP_A, "buyers": ["Kris"]},
                    GROUP_B,
                ],
                "empty": "月中暫無款項請款",
            }
        ),
        encoding="utf-8",
    )
    assert run_sync(root, source, dry_run=False) == "updated"
    public = json.loads((root / "data" / "public.json").read_text(encoding="utf-8"))
    names = {row["name"] for row in public["billing"]["buyers"]}
    assert names == {"Kris", "買家乙"}
    by_buyer = {row["name"]: row["total"] for row in public["billing"]["buyers"]}
    assert by_buyer["Kris"] == 11
    assert by_buyer["買家乙"] == 22


def _gin_group_bundle():
    filtered = {
        "groupBuy": {
            **base_group(GROUP_FILTER),
            "name": "BANPRESTO 測試銀魂",
            "currency": "CNY",
            "status": "arrived",
            "startedAt": "2026-04-20",
            "chargeRate": "4.87607",
        },
        "orders": [
            _order("kris", "Kris", [_item("k1", "銀时", "69", "packing"), _item("k2", "土方", "69", "packing")], False),
            _order("mita", "Mita", [_item("m1", "銀时", "69", "packing"), _item("m2", "土方", "69", "packing")], False),
            _order("fang", "小芳", [_item("f1", "土方", "69", "packing")], False),
            _order("wei", "小衛", [_item("w1", "銀时", "69"), _item("w2", "冲田", "69")], False, status="completed"),
            _order("rice", "白米", [_item("r1", "銀时", "69", "packing")], False, payments=[{"amount": "306", "paidAt": "2026-11-01", "note": "測試抵扣"}]),
            _order("self", "阿蝶", [_item("s1", "土方", "69"), _item("s2", "銀时", "69")], True, status="completed"),
        ],
        "fees": [],
        "settlement": {
            "orders": [
                _settle("kris", "604", "0", "604"),
                _settle("mita", "604", "0", "604"),
                _settle("fang", "306", "0", "306"),
                _settle("wei", "604", "0", "604"),
                _settle("rice", "306", "306", "0"),
                _settle("self", "0", "0", "0"),
            ]
        },
    }
    plain = {
        "groupBuy": {**base_group(GROUP_PLAIN), "name": "對照團", "currency": "TWD"},
        "orders": [_order("plain-kris", "Kris", [_item("p1", "對照品", "100")], False)],
        "fees": [],
        "settlement": {"orders": [_settle("plain-kris", "100", "0", "100")]},
    }
    items = {
        GROUP_FILTER: [
            flat(row["id"], GROUP_FILTER, row["name"], row["unitPrice"], "")
            | {"status": row["status"]}
            for order in filtered["orders"]
            for row in order["items"]
        ],
        GROUP_PLAIN: [flat("p1", GROUP_PLAIN, "對照品", "100", "")],
    }
    summary = [
        {"name": "Kris", "charge": "704", "paidSum": "0", "remaining": "704"},
        {"name": "Mita", "charge": "604", "paidSum": "0", "remaining": "604"},
        {"name": "小芳", "charge": "306", "paidSum": "0", "remaining": "306"},
        {"name": "小衛", "charge": "604", "paidSum": "0", "remaining": "604"},
        {"name": "白米", "charge": "306", "paidSum": "306", "remaining": "0"},
        {"name": "阿蝶", "charge": "0", "paidSum": "0", "remaining": "0", "isSelfOnly": True},
    ]
    return [filtered, plain], items, summary


def _item(item_id, name, price, status="ordered"):
    row = item(item_id, name, price, "")
    row["status"] = status
    return row


def _order(order_id, buyer, items, is_self, status=None, payments=None):
    if status:
        for row in items:
            row["status"] = status
    return {
        "id": order_id,
        "buyerName": buyer,
        "isSelf": is_self,
        "items": items,
        "payments": payments or [],
    }


def _settle(order_id, charge, paid, remaining):
    return {
        "orderId": order_id,
        "goodsCharge": charge,
        "feeCharge": "0",
        "charge": charge,
        "paidSum": paid,
        "remaining": remaining,
    }
