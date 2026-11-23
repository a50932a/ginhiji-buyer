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
    QIANSHOU_GROUP = "01a20860e3aa7394aad9c2e3b92bb0b9"
    HEINEKORO4_GROUP = "01a208722e4170febc1a7c29f89b9f9b"
    BIBISAMA_GROUP = "01a2088d7816720ba3738e4d29c119a6"
    KABUKI_GROUP = "01a208b44d5c70ff86a74d739fb123c5"
    allow_ids = set(allow["include"])
    assert published <= allow_ids
    assert NEW_GROUP in published
    assert XIANYU_GROUP in allow_ids
    assert CHIBAOBAO_GROUP in allow_ids
    assert SAKAMOTO_GROUP in allow_ids
    assert QIANSHOU_GROUP in allow_ids
    assert HEINEKORO4_GROUP in allow_ids
    assert BIBISAMA_GROUP in allow_ids
    assert KABUKI_GROUP in allow_ids
    assert len(allow_ids) == 147
    assert allow_ids - published <= {KABUKI_GROUP}
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
    if QIANSHOU_GROUP in published:
        qianshou = next(item for item in public["gbs"] if item["id"] == QIANSHOU_GROUP)
        charges = {order["b"]: order["charge"] for order in qianshou["o"]}
        assert charges["白米"] == 136
        assert charges["Mita"] == 136
        assert qianshou["st"] == "closed"
        assert qianshou["cur"] == "CNY"
        self_orders = [order for order in qianshou["o"] if order["b"] == "阿蝶"]
        assert len(self_orders) == 1 and self_orders[0]["self"]
        item_names = {item[0] for order in qianshou["o"] for item in order["it"]}
        assert any("坂田银时" in name for name in item_names)
        assert any("土方十四郎" in name for name in item_names)
        assert {item[3] for order in qianshou["o"] for item in order["it"]} == {"shipped"}
    if HEINEKORO4_GROUP in published:
        heinekoro4 = next(item for item in public["gbs"] if item["id"] == HEINEKORO4_GROUP)
        charges = {order["b"]: order["charge"] for order in heinekoro4["o"]}
        assert charges == {
            "苦骸": 824,
            "いさぎ": 824,
            "優尼": 824,
            "拿鐵": 824,
            "鹹魚": 824,
            "淑麗": 824,
            "草凡": 824,
            "Mita": 824,
            "小雯": 824,
            "白米": 824,
        }
        assert heinekoro4["st"] == "closed"
        assert heinekoro4["cur"] == "JPY"
        assert heinekoro4["img"]
        assert all(not order["self"] for order in heinekoro4["o"])
        item_names = {item[0] for order in heinekoro4["o"] for item in order["it"]}
        assert item_names == {"ハイネコロク4 銀土再録集"}
        assert {item[3] for order in heinekoro4["o"] for item in order["it"]} == {"ordered"}
    if BIBISAMA_GROUP in published:
        bibisama = next(item for item in public["gbs"] if item["id"] == BIBISAMA_GROUP)
        charges = {order["b"]: order["charge"] for order in bibisama["o"]}
        assert charges == {
            "阿蝶": 0,
            "魚魚": 5032,
            "草凡": 1845,
            "星星": 1845,
            "Mita": 5032,
            "佐佐": 2516,
            "扣咩": 2516,
        }
        assert bibisama["st"] == "closed"
        assert bibisama["cur"] == "TWD"
        assert bibisama["img"]
        adie = next(order for order in bibisama["o"] if order["b"] == "阿蝶")
        assert adie["self"]
        assert all(order["self"] for order in bibisama["o"] if order["b"] == "阿蝶")
        assert all(not order["self"] for order in bibisama["o"] if order["b"] != "阿蝶")
        assert "星星" in charges and "Starry Sky" not in charges
        buyer_names = {buyer["n"] for buyer in public["buyers"]}
        assert "星星" in buyer_names
        item_names = {item[0] for order in bibisama["o"] for item in order["it"]}
        assert "真選組外套（Bomber Jacket / Black / M-L）" in item_names
        assert "萬事屋外套（Bomber Jacket / White / M-L）" in item_names
        assert "定春毛衣（Sadaharu Sweater / M-L）" in item_names
        assert "雪中萬事屋毛衣（Yorozuya Snow Day Sweater / XS-S）" in item_names
        yu_black = next(
            item[3]
            for order in bibisama["o"] if order["b"] == "魚魚"
            for item in order["it"] if item[0] == "真選組外套（Bomber Jacket / Black / XS-S）"
        )
        assert yu_black == "recorded"
        assert {
            item[3]
            for order in bibisama["o"]
            for item in order["it"]
            if not (order["b"] == "魚魚" and item[0] == "真選組外套（Bomber Jacket / Black / XS-S）")
        } == {"ordered"}
        assert all(item[5] for order in bibisama["o"] for item in order["it"])
    if KABUKI_GROUP in published:
        kabuki = next(item for item in public["gbs"] if item["id"] == KABUKI_GROUP)
        charges = {order["b"]: order["charge"] for order in kabuki["o"]}
        assert charges == {
            "白米": 412,
            "Mita": 412,
            "淑麗": 541,
            "阿辰": 412,
            "Kris": 412,
            "阿魯": 592,
            "小雯": 412,
            "草凡": 592,
            "茫狗": 412,
            "阿蝶": 0,
        }
        assert kabuki["st"] == "closed"
        assert kabuki["cur"] == "CNY"
        assert kabuki["img"]
        adie = next(order for order in kabuki["o"] if order["b"] == "阿蝶")
        assert adie["self"]
        assert all(not order["self"] for order in kabuki["o"] if order["b"] != "阿蝶")
        item_names = {item[0] for order in kabuki["o"] for item in order["it"]}
        assert "笔记本（预售送亚克力+贴纸）" in item_names
        assert "明信片套组" in item_names
        assert "票根套组" in item_names
        assert {item[3] for order in kabuki["o"] for item in order["it"]} == {"ordered"}
        assert all(item[5] for order in kabuki["o"] for item in order["it"])
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
        "01a1fc9c2c6277909ddb902913e68fc5",
    ]
    assert set(end_ids) <= published
    assert CHIBAOBAO_GROUP not in billing_ids
    assert CHIBAOBAO_GROUP not in end_ids
    assert SAKAMOTO_GROUP not in billing_ids
    assert SAKAMOTO_GROUP in end_ids
    assert QIANSHOU_GROUP not in billing_ids
    assert QIANSHOU_GROUP not in end_ids
    assert HEINEKORO4_GROUP not in billing_ids
    assert HEINEKORO4_GROUP not in end_ids
    assert BIBISAMA_GROUP not in billing_ids
    assert BIBISAMA_GROUP not in end_ids
    assert KABUKI_GROUP not in billing_ids
    assert KABUKI_GROUP not in end_ids
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
