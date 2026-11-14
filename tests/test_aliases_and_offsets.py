"""買家別名合併，以及以備註標示抵扣。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sync.errors import SchemaError
from sync.project import parse_buyer_aliases, parse_offset_notes, project_publication
from sync.sync_orders import load_buyer_aliases, load_offset_notes, run_sync
from tests.test_project import base_group, flat, item
from tests.test_sync_run import FakeSource, site_root


def test_parse_buyer_aliases_flattens_and_rejects_cycles():
    assert parse_buyer_aliases({"苒": "苒苒"}) == {"苒": "苒苒"}
    assert parse_buyer_aliases({"甲": "乙", "乙": "丙"}) == {"甲": "丙", "乙": "丙"}
    with pytest.raises(SchemaError, match="循環"):
        parse_buyer_aliases({"甲": "乙", "乙": "甲"})
    with pytest.raises(SchemaError, match="自己"):
        parse_buyer_aliases({"苒苒": "苒苒"})
    with pytest.raises(SchemaError, match="不正確"):
        parse_buyer_aliases({"苒": " 苒苒"})


def test_parse_offset_notes_rejects_blank_or_duplicate():
    assert parse_offset_notes(["銀土T、銀土立牌"]) == frozenset({"銀土T、銀土立牌"})
    with pytest.raises(SchemaError, match="不正確"):
        parse_offset_notes([" 抵扣 "])
    with pytest.raises(SchemaError, match="重複"):
        parse_offset_notes(["抵扣", "抵扣"])
    assert parse_offset_notes(None) == frozenset()
    assert parse_buyer_aliases(None) == {}


def test_missing_alias_and_note_files_are_empty(tmp_path: Path):
    assert load_buyer_aliases(tmp_path / "buyer_aliases.json") == {}
    assert load_offset_notes(tmp_path / "offset_notes.json") == frozenset()


def test_offset_note_marks_deduction_even_if_previous_flag_was_zero():
    group_id = "a" * 32
    previous = {
        "gbs": [
            {
                "id": group_id,
                "o": [{"b": "草凡", "pay": [[1365, "2026-11-08", "銀土T、銀土立牌", 0]]}],
            }
        ]
    }
    public, _images = _one_buyer_publication(
        group_id,
        "草凡",
        [{"amount": "1365", "paidAt": "2026-11-08", "note": "銀土T、銀土立牌"}],
        charge="1365",
        paid="1365",
        remaining="0",
        previous=previous,
        offset_notes=["銀土T、銀土立牌"],
    )
    order = public["gbs"][0]["o"][0]
    assert order["pay"] == [[1365, "2026-11-08", "銀土T、銀土立牌", 1]]
    buyer = public["buyers"][0]
    assert buyer["n"] == "草凡"
    assert buyer["paid"] == 1365
    assert buyer["rem"] == 0
    assert buyer["off"] == 1365
    assert buyer["offs"] == [["測試團", "2026-11-08", 1365, "銀土T、銀土立牌"]]


def test_unlisted_notes_stay_regular_and_previous_flags_are_kept():
    group_id = "b" * 32
    previous = {
        "gbs": [
            {
                "id": group_id,
                "o": [{"b": "白米", "pay": [[306, "2026-11-01", "跟白米買銀魂日和銀土髮夾", 1]]}],
            }
        ]
    }
    public, _images = _one_buyer_publication(
        group_id,
        "白米",
        [
            {"amount": "306", "paidAt": "2026-11-01", "note": "跟白米買銀魂日和銀土髮夾"},
            {"amount": "200", "paidAt": "2026-11-02", "note": "匯款"},
        ],
        charge="506",
        paid="506",
        remaining="0",
        previous=previous,
        offset_notes=["銀土T、銀土立牌"],
    )
    flags = {payment[2]: payment[3] for payment in public["gbs"][0]["o"][0]["pay"]}
    assert flags == {"跟白米買銀魂日和銀土髮夾": 1, "匯款": 0}
    buyer = public["buyers"][0]
    assert buyer["off"] == 306
    assert buyer["paid"] == 506


def test_buyer_aliases_merge_reconciliation_and_billing_but_keep_order_names():
    early = "c" * 32
    later = "d" * 32
    details, items, summary = _alias_bundle(early, later)
    public, _images = project_publication(
        details,
        items,
        summary,
        previous=None,
        billing_ids=[early, later],
        fetched_at="2026-11-14 14:00",
        empty_text="月中暫無款項請款",
        buyer_aliases={"苒": "苒苒"},
    )
    names = {order["b"] for group in public["gbs"] for order in group["o"]}
    assert names == {"苒", "苒苒"}
    buyers = {buyer["n"]: buyer for buyer in public["buyers"]}
    assert "苒" not in buyers
    merged = buyers["苒苒"]
    assert merged["gc"] == 2
    assert merged["q"] == 7
    assert merged["charge"] == 1870
    assert merged["paid"] == 1870
    assert merged["rem"] == 0
    billing_names = {row["name"] for row in public["billing"]["buyers"]}
    assert billing_names == set()  # both paid in full


def test_buyer_aliases_merge_unpaid_billing_totals():
    early = "e" * 32
    later = "f" * 32
    details, items, summary = _alias_bundle(early, later, paid=False)
    public, _images = project_publication(
        details,
        items,
        summary,
        previous=None,
        billing_ids=[early, later],
        fetched_at="2026-11-14 14:00",
        empty_text="月中暫無款項請款",
        buyer_aliases={"苒": "苒苒"},
    )
    billing = {row["name"]: row for row in public["billing"]["buyers"]}
    assert "苒" not in billing
    assert billing["苒苒"]["total"] == 1870
    assert [item["amount"] for item in billing["苒苒"]["items"]] == [1559, 311]


def test_sync_loads_alias_and_offset_config(tmp_path: Path):
    from tests.test_sync_run import GROUP_A, GROUP_B, bundle, detail_for

    groups, items, buyers = bundle()
    groups[GROUP_A] = detail_for(GROUP_A, "苒", "11")
    groups[GROUP_B] = detail_for(GROUP_B, "苒苒", "22")
    groups[GROUP_A]["orders"][0]["payments"] = [
        {"amount": "11", "paidAt": "2026-11-08", "note": "銀土T、銀土立牌"}
    ]
    groups[GROUP_A]["settlement"]["orders"][0]["paidSum"] = "11"
    groups[GROUP_A]["settlement"]["orders"][0]["remaining"] = "0"
    buyers = [
        {"name": "苒", "charge": "11", "paidSum": "11", "remaining": "0"},
        {"name": "苒苒", "charge": "22", "paidSum": "0", "remaining": "22"},
    ]
    source = FakeSource(groups, items, buyers)
    root = site_root(tmp_path, [GROUP_A, GROUP_B])
    (root / "sync" / "buyer_aliases.json").write_text(
        json.dumps({"aliases": {"苒": "苒苒"}}),
        encoding="utf-8",
    )
    (root / "sync" / "offset_notes.json").write_text(
        json.dumps({"notes": ["銀土T、銀土立牌"]}),
        encoding="utf-8",
    )
    (root / "sync" / "billing_groups.json").write_text(
        json.dumps({"include": [GROUP_A, GROUP_B], "empty": "月中暫無款項請款"}),
        encoding="utf-8",
    )
    assert run_sync(root, source, dry_run=False) == "updated"
    public = json.loads((root / "data" / "public.json").read_text(encoding="utf-8"))
    names = {buyer["n"]: buyer for buyer in public["buyers"]}
    assert "苒" not in names
    assert names["苒苒"]["charge"] == 33
    assert names["苒苒"]["paid"] == 11
    assert names["苒苒"]["rem"] == 22
    assert names["苒苒"]["off"] == 11
    bill = {row["name"]: row for row in public["billing"]["buyers"]}
    assert "苒" not in bill
    assert bill["苒苒"]["total"] == 22
    assert public["gbs"][0]["o"][0]["b"] in {"苒", "苒苒"}


def _one_buyer_publication(group_id, buyer, payments, *, charge, paid, remaining, previous, offset_notes):
    detail = {
        "groupBuy": base_group(group_id),
        "orders": [
            {
                "id": "order-1",
                "buyerName": buyer,
                "isSelf": False,
                "items": [item("item-1", "品項", "100", "")],
                "payments": payments,
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": "order-1",
                    "goodsCharge": charge,
                    "feeCharge": "0",
                    "charge": charge,
                    "paidSum": paid,
                    "remaining": remaining,
                }
            ]
        },
    }
    return project_publication(
        [detail],
        {group_id: [flat("item-1", group_id, "品項", "100", "")]},
        [{"name": buyer, "charge": charge, "paidSum": paid, "remaining": remaining}],
        previous=previous,
        billing_ids=[],
        fetched_at="2026-11-14 14:00",
        empty_text="沒有",
        offset_notes=offset_notes,
    )


def _alias_bundle(early_id, later_id, paid=True):
    early_paid = "1559" if paid else "0"
    later_paid = "311" if paid else "0"
    early_rem = "0" if paid else "1559"
    later_rem = "0" if paid else "311"
    early = {
        "groupBuy": {**base_group(early_id), "name": "東武測試團", "startedAt": "2026-07-11", "currency": "TWD"},
        "orders": [
            {
                "id": "order-ran",
                "buyerName": "苒",
                "isSelf": False,
                "items": [item(f"early-{i}", f"品{i}", "100", "") for i in range(6)],
                "payments": ([{"amount": "1559", "paidAt": "2026-09-06", "note": "轉帳"}] if paid else []),
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": "order-ran",
                    "goodsCharge": "1559",
                    "feeCharge": "0",
                    "charge": "1559",
                    "paidSum": early_paid,
                    "remaining": early_rem,
                }
            ]
        },
    }
    later = {
        "groupBuy": {**base_group(later_id), "name": "共鸣測試團", "startedAt": "2026-10-17", "currency": "TWD"},
        "orders": [
            {
                "id": "order-ranran",
                "buyerName": "苒苒",
                "isSelf": False,
                "items": [item("later-1", "品項", "100", "")],
                "payments": ([{"amount": "311", "paidAt": "2026-10-30", "note": "收清尾款"}] if paid else []),
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": "order-ranran",
                    "goodsCharge": "311",
                    "feeCharge": "0",
                    "charge": "311",
                    "paidSum": later_paid,
                    "remaining": later_rem,
                }
            ]
        },
    }
    items = {
        early_id: [flat(f"early-{i}", early_id, f"品{i}", "100", "") for i in range(6)],
        later_id: [flat("later-1", later_id, "品項", "100", "")],
    }
    summary = [
        {"name": "苒", "charge": "1559", "paidSum": early_paid, "remaining": early_rem},
        {"name": "苒苒", "charge": "311", "paidSum": later_paid, "remaining": later_rem},
    ]
    return [early, later], items, summary
