"""確認公開範圍仍是允許清單，而且工作流程沒有排程。"""

from __future__ import annotations

import json
from pathlib import Path

from sync.project import parse_billing_include, validate_public
from sync.sync_orders import load_buyer_aliases, load_offset_notes

ROOT = Path(__file__).resolve().parents[1]
NEW_GROUP = "01a1bb0ec8207669a9dcc46e4ed9fb32"
BANNED_KEYS = {
    "costRate",
    "profit",
    "totalCost",
    "feeCostTotal",
    "selfCost",
    "costShare",
    "members",
    "payouts",
    "payout",
    "role",
    "email",
    "token",
    "password",
    "bank",
    "card",
    "cardNumber",
    "credential",
    "accessToken",
}


def test_published_snapshot_matches_the_allowlist():
    public = json.loads((ROOT / "data" / "public.json").read_text(encoding="utf-8"))
    allow = json.loads((ROOT / "sync" / "allowlist.json").read_text(encoding="utf-8"))
    validate_public(public)
    published = {group["id"] for group in public["gbs"]}
    XIANYU_GROUP = "01a1d8a326e773d9be07c6063788e9dd"
    CHIBAOBAO_GROUP = "01a1fccfa14f7686bd3220d143d1d87d"
    SAKAMOTO_GROUP = "01a1fc9c2c6277909ddb902913e68fc5"
    allow_ids = set(allow["include"])
    assert published <= allow_ids
    assert NEW_GROUP in published
    assert XIANYU_GROUP in allow_ids
    assert CHIBAOBAO_GROUP in allow_ids
    assert SAKAMOTO_GROUP in allow_ids
    assert len(allow_ids) == 143
    assert allow_ids - published <= {SAKAMOTO_GROUP}
    if XIANYU_GROUP in published:
        xianyu = next(item for item in public["gbs"] if item["id"] == XIANYU_GROUP)
        charges = {order["b"]: order["charge"] for order in xianyu["o"]}
        assert charges["Mita"] == 4070
        assert xianyu["st"] == "closed"
        assert xianyu["cur"] == "CNY"
        assert xianyu["img"]
    if CHIBAOBAO_GROUP in published:
        chibaobao = next(item for item in public["gbs"] if item["id"] == CHIBAOBAO_GROUP)
        charges = {order["b"]: order["charge"] for order in chibaobao["o"]}
        assert charges["Mita"] == 588
        assert chibaobao["st"] == "closed"
        assert chibaobao["cur"] == "CNY"
        self_orders = [order for order in chibaobao["o"] if order["b"] == "阿蝶"]
        assert len(self_orders) == 1 and self_orders[0]["self"]
        item_names = {item[0] for order in chibaobao["o"] for item in order["it"]}
        assert any("坂田银时" in name for name in item_names)
        assert any("土方十四郎" in name for name in item_names)
        assert {item[3] for order in chibaobao["o"] for item in order["it"]} == {"shipped"}
    if SAKAMOTO_GROUP in published:
        sakamoto = next(item for item in public["gbs"] if item["id"] == SAKAMOTO_GROUP)
        charges = {order["b"]: order["charge"] for order in sakamoto["o"]}
        assert charges["苦骸"] == 50
        assert sakamoto["st"] == "arrived"
        assert sakamoto["cur"] == "TWD"
        item_names = {item[0] for order in sakamoto["o"] for item in order["it"]}
        assert any("坂本辰馬" in name or "辰馬色紙" in name for name in item_names)
        assert {item[3] for order in sakamoto["o"] for item in order["it"]} == {"packing"}
    group = next(item for item in public["gbs"] if item["id"] == NEW_GROUP)
    charges = {order["b"]: order["charge"] for order in group["o"]}
    assert charges["草凡"] == 800
    assert charges["阿魯"] == 724
    assert group["st"] == "closed"
    assert {item[3] for order in group["o"] for item in order["it"]} == {"ordered"}
    assert _banned_keys(public) == set()
    billing = json.loads((ROOT / "sync" / "billing_groups.json").read_text(encoding="utf-8"))
    billing_entries = parse_billing_include(billing["include"], allow_empty=False)
    billing_ids = [entry.id for entry in billing_entries]
    assert set(billing_ids) <= published
    assert NEW_GROUP not in billing_ids
    banpresto = next(entry for entry in billing_entries if entry.id == "01a19329f6517208831dbe5a9077520e")
    assert banpresto.buyers == ("Kris", "Mita")
    assert sum(1 for entry in billing_entries if entry.buyers is not None) == 1
    end = json.loads((ROOT / "sync" / "billing_month_end.json").read_text(encoding="utf-8"))
    end_entries = parse_billing_include(end["include"], allow_empty=False)
    end_ids = [entry.id for entry in end_entries]
    assert end["empty"] == "月底暫無款項請款"
    assert end_ids == [
        "01a16ed8cba1708aa66f2506ad1c8ca2",
        "01a192e2ba2973d3a2169e49b1f7b5a6",
        "01a193196d5b752d87a6d8ba3e6d874b",
        "01a192996ec77608a91262c8086a0eef",
    ]
    assert set(end_ids) <= published
    assert CHIBAOBAO_GROUP not in billing_ids
    assert CHIBAOBAO_GROUP not in end_ids
    assert SAKAMOTO_GROUP not in billing_ids
    assert SAKAMOTO_GROUP not in end_ids
    assert all(entry.buyers is None for entry in end_entries)
    assert set(billing_ids).isdisjoint(end_ids)
    assert "billingEnd" in public
    assert set(public["billingEnd"]) == {"items", "empty", "buyers"}
    aliases = load_buyer_aliases(ROOT / "sync" / "buyer_aliases.json")
    assert aliases.get("苒") == "苒苒"
    notes = load_offset_notes(ROOT / "sync" / "offset_notes.json")
    assert "銀土T、銀土立牌" in notes
    names = {buyer["n"] for buyer in public["buyers"]}
    if "苒" in names and "苒苒" in names:
        pass
    else:
        assert "苒苒" in names and "苒" not in names
        merged = next(buyer for buyer in public["buyers"] if buyer["n"] == "苒苒")
        assert merged["charge"] == 1870
        assert merged["paid"] == 1870
        assert merged["rem"] == 0
        assert merged["gc"] == 2
        assert merged["q"] == 7
    caofan = next(buyer for buyer in public["buyers"] if buyer["n"] == "草凡")
    caofan_offs = [
        payment
        for group in public["gbs"]
        for order in group["o"]
        if order["b"] == "草凡"
        for payment in order["pay"]
        if payment[2] == "銀土T、銀土立牌"
    ]
    if caofan_offs and all(payment[3] for payment in caofan_offs):
        assert caofan["off"] == 1365
        assert len(caofan["offs"]) == 4


def test_page_loads_the_projection_instead_of_embedding_it():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "data/public.json" in html
    assert "const DATA = {" not in html
    assert "含抵扣" in html
    assert "o.pay.filter(p=>p[3])" in html
    notice = (
        "付款注意事項：",
        "月初請款請於每月4日前付款。",
        "月中請款請於每月17日前付款。",
        "月底請款請於每月25日前付款。",
    )
    for line in notice:
        assert line in html
    static = html.split('<div id="billing"></div>', 1)[1].split("</section>", 1)[0]
    for line in notice:
        assert line in static
    assert "bl-note" in static
    assert html.count('class="panel billing"') == 1
    section = html.split('<section class="panel billing">', 1)[1].split("</section>", 1)[0]
    assert "近期請款預告" in section
    assert "<h3>月中請款</h3>" in section
    assert "<h3>月底請款</h3>" in section
    assert 'id="billing"' in section
    assert 'id="billingEnd"' in section
    assert "bl-note" in section
    assert section.index("<h3>月中請款</h3>") < section.index('id="billing"')
    assert section.index('id="billing"') < section.index("<h3>月底請款</h3>")
    assert section.index('id="billingEnd"') < section.index("付款注意事項：")
    assert "月底請款預告" not in html
    assert html.count("付款注意事項：") == 1
    assert 'renderBilling("billingEnd", DATA.billingEnd, "月底暫無款項請款")' in html
    assert 'renderBilling("billing", DATA.billing, "月中暫無款項請款")' in html
    public = json.loads((ROOT / "data" / "public.json").read_text(encoding="utf-8"))
    assert "付款注意事項" not in json.dumps(public, ensure_ascii=False)
    assert "costRate" not in html
    assert "ORDERS_API_TOKEN" not in html
    assert "每天" not in html
    assert "每日" not in html
    workflow = (ROOT / ".github" / "workflows" / "sync-orders.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow
    assert "schedule" not in workflow
    assert "cron" not in workflow


def _banned_keys(value, found=None):
    found = found if found is not None else set()
    if isinstance(value, dict):
        found.update(BANNED_KEYS.intersection(value))
        for child in value.values():
            _banned_keys(child, found)
    elif isinstance(value, list):
        for child in value:
            _banned_keys(child, found)
    return found
