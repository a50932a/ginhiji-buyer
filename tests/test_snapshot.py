"""確認公開範圍仍是允許清單，而且工作流程沒有排程。"""

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


def test_published_snapshot_matches_the_allowlist():
    public = json.loads((ROOT / "data" / "public.json").read_text(encoding="utf-8"))
    allow = json.loads((ROOT / "sync" / "allowlist.json").read_text(encoding="utf-8"))
    validate_public(public)
    published = {group["id"] for group in public["gbs"]}
    assert published == set(allow["include"])
    assert len(published) == 140
    assert NEW_GROUP in published
    group = next(item for item in public["gbs"] if item["id"] == NEW_GROUP)
    charges = {order["b"]: order["charge"] for order in group["o"]}
    assert charges["草凡"] == 800
    assert charges["阿魯"] == 724
    assert group["st"] == "closed"
    assert {item[3] for order in group["o"] for item in order["it"]} == {"ordered"}
    assert _banned_keys(public) == set()
    billing = json.loads((ROOT / "sync" / "billing_groups.json").read_text(encoding="utf-8"))
    assert set(billing["include"]) <= published
    assert NEW_GROUP not in billing["include"]


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
