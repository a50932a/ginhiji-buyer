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
    allow_ids = set(allow["include"])
    assert published <= allow_ids
    assert NEW_GROUP in published
    assert XIANYU_GROUP in allow_ids
    assert len(allow_ids) == 141
    assert allow_ids - published <= {XIANYU_GROUP}
    if XIANYU_GROUP in published:
        xianyu = next(item for item in public["gbs"] if item["id"] == XIANYU_GROUP)
        charges = {order["b"]: order["charge"] for order in xianyu["o"]}
        assert charges["Mita"] == 4070
        assert xianyu["st"] == "closed"
        assert xianyu["cur"] == "CNY"
        assert xianyu["img"]
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
