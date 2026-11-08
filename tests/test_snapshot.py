"""確認目前提交的公開快照仍是既有範圍，沒有把新團的金額寫進去。"""

from __future__ import annotations

import json
from pathlib import Path

from sync.project import validate_public

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


def test_published_snapshot_keeps_the_existing_scope():
    public = json.loads((ROOT / "data" / "public.json").read_text(encoding="utf-8"))
    validate_public(public)
    assert public["fetchedAt"] == "2026-11-04 22:41"
    assert len(public["gbs"]) == 139
    assert len(public["buyers"]) == 39
    assert len(public["billing"]["items"]) == 14
    assert sum(len(order["it"]) for group in public["gbs"] for order in group["o"]) == 790
    assert NEW_GROUP not in {group["id"] for group in public["gbs"]}
    assert _banned_keys(public) == set()
    dates = [group["dt"] for group in public["gbs"]]
    assert min(dates) == "2026-02-01"
    assert max(dates) == "2026-11-01"


def test_allowlist_is_the_snapshot_plus_one_reviewed_id():
    allow = json.loads((ROOT / "sync" / "allowlist.json").read_text(encoding="utf-8"))
    public = json.loads((ROOT / "data" / "public.json").read_text(encoding="utf-8"))
    published = [group["id"] for group in public["gbs"]]
    assert allow["include"][0] == NEW_GROUP
    assert allow["include"][1:] == published
    billing = json.loads((ROOT / "sync" / "billing_groups.json").read_text(encoding="utf-8"))
    assert set(billing["include"]) <= set(published)
    assert len(billing["include"]) == 14
    assert NEW_GROUP not in billing["include"]


def test_page_loads_the_projection_instead_of_embedding_it():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "data/public.json" in html
    assert "const DATA = {" not in html
    assert "costRate" not in html
    assert "ORDERS_API_TOKEN" not in html


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
