"""同步程序測試。失敗時必須留著上一筆公開資料。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from io import BytesIO

from sync.errors import AuthError, MissingImage, SchemaError
from sync.images import sha256_bytes
from sync.sync_orders import ProjectionFile, run_sync
from tests.test_project import base_group, flat, item


GROUP_A = "a" * 32
GROUP_B = "b" * 32
GROUP_SECRET = "e" * 32


class FakeSource:
    def __init__(self, groups: dict[str, dict], items: dict[str, list], buyers: list[dict]):
        self.groups = groups
        self.items = items
        self.buyers = buyers
        self.group_calls = []
        self.item_calls = []
        self.image_calls = []
        self.fail_list = None

    def list_groups(self):
        if self.fail_list:
            raise self.fail_list
        return [{"id": group_id} for group_id in self.groups]

    def get_group(self, group_id):
        self.group_calls.append(group_id)
        return self.groups[group_id]

    def get_items(self, group_id):
        self.item_calls.append(group_id)
        return self.items[group_id]

    def buyers_summary(self, group_ids):
        assert set(group_ids) <= set(self.groups)
        assert GROUP_SECRET not in group_ids
        names = {self.groups[group_id]["orders"][0]["buyerName"] for group_id in group_ids}
        return [row for row in self.buyers if row["name"] in names]

    def stat_image(self, url):
        return '"same"'

    def get_image(self, url):
        self.image_calls.append(url)
        buffer = BytesIO()
        Image.new("RGB", (40, 20), "red").save(buffer, format="JPEG")
        return buffer.getvalue(), '"new"'


def test_only_allowlisted_groups_are_written(tmp_path: Path):
    source = FakeSource(*bundle())
    root = site_root(tmp_path, [GROUP_A])
    assert run_sync(root, source, dry_run=False) == "updated"
    public = json.loads((root / "data" / "public.json").read_text(encoding="utf-8"))
    assert [group["id"] for group in public["gbs"]] == [GROUP_A]
    assert source.group_calls == [GROUP_A]
    assert GROUP_SECRET not in source.group_calls
    assert run_sync(root, source, dry_run=False) == "noop"


def test_auth_failure_keeps_last_public_file(tmp_path: Path):
    source = FakeSource(*bundle())
    root = site_root(tmp_path, [GROUP_A])
    run_sync(root, source, dry_run=False)
    before = (root / "data" / "public.json").read_bytes()
    source.fail_list = AuthError("來源拒絕授權")
    with pytest.raises(AuthError):
        run_sync(root, source, dry_run=False)
    assert (root / "data" / "public.json").read_bytes() == before
    assert list((root / "data").glob(".*")) == []


def test_missing_published_group_does_not_shrink_the_file(tmp_path: Path):
    groups, items, buyers = bundle()
    source = FakeSource(groups, items, buyers)
    root = site_root(tmp_path, [GROUP_A, GROUP_B])
    run_sync(root, source, dry_run=False)
    before = (root / "data" / "public.json").read_bytes()
    del source.groups[GROUP_B]
    with pytest.raises(SchemaError, match="先前已公開"):
        run_sync(root, source, dry_run=False)
    assert (root / "data" / "public.json").read_bytes() == before


def test_new_allowlisted_id_missing_from_source_is_skipped(tmp_path: Path):
    source = FakeSource(*bundle())
    root = site_root(tmp_path, [GROUP_A, "f" * 32])
    assert run_sync(root, source, dry_run=False) == "updated"
    public = json.loads((root / "data" / "public.json").read_text(encoding="utf-8"))
    assert [group["id"] for group in public["gbs"]] == [GROUP_A]


def test_summary_mismatch_writes_nothing(tmp_path: Path):
    groups, items, buyers = bundle()
    buyers[0]["charge"] = "1"
    source = FakeSource(groups, items, buyers)
    root = site_root(tmp_path, [GROUP_A])
    with pytest.raises(SchemaError, match="不一致"):
        run_sync(root, source, dry_run=False)
    assert not (root / "data" / "public.json").exists()


def test_existing_image_is_not_reencoded_when_etag_matches(tmp_path: Path):
    groups, items, buyers = bundle()
    groups[GROUP_A]["groupBuy"]["image"] = "/api/images/abc123def456"
    source = FakeSource(groups, items, buyers)
    root = site_root(tmp_path, [GROUP_A])
    raw = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(raw, format="JPEG")
    payload = raw.getvalue()
    for folder in ("l", "t"):
        path = root / "img" / folder / "abc123def456.jpg"
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
    digest = sha256_bytes(payload)
    cache = {"images": {"abc123def456": {"etag": '"same"', "sha256": digest}}}
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "image-cache.json").write_text(json.dumps(cache), encoding="utf-8")
    run_sync(root, source, dry_run=False)
    assert source.image_calls == []
    assert (root / "img" / "l" / "abc123def456.jpg").read_bytes() == payload


def test_projection_file_rejects_cost_and_profit(tmp_path: Path):
    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps({"groups": [{"groupBuy": {"costRate": "0.2"}}], "items": {}, "buyers": []}), encoding="utf-8")
    with pytest.raises(SchemaError, match="不公開"):
        ProjectionFile(path)


def test_foreign_items_abort(tmp_path: Path):
    groups, items, buyers = bundle()
    items[GROUP_A][0]["groupBuyId"] = GROUP_SECRET
    source = FakeSource(groups, items, buyers)
    root = site_root(tmp_path, [GROUP_A])
    with pytest.raises(SchemaError, match="沒有指定"):
        run_sync(root, source, dry_run=False)
    assert not (root / "data" / "public.json").exists()


def test_missing_new_image_aborts_without_a_public_file(tmp_path: Path):
    groups, items, buyers = bundle()
    groups[GROUP_A]["orders"][0]["items"][0]["image"] = "/api/images/abc123def456"
    items[GROUP_A][0]["image"] = "/api/images/abc123def456"
    source = FakeSource(groups, items, buyers)

    def missing(_url):
        raise MissingImage("圖片不存在")

    source.get_image = missing
    root = site_root(tmp_path, [GROUP_A])
    with pytest.raises(MissingImage):
        run_sync(root, source, dry_run=False)
    assert not (root / "data" / "public.json").exists()


def bundle():
    groups = {
        GROUP_A: detail_for(GROUP_A, "買家甲", "11"),
        GROUP_B: detail_for(GROUP_B, "買家乙", "22"),
        GROUP_SECRET: detail_for(GROUP_SECRET, "不公開的人", "99"),
    }
    items = {
        group_id: [flat(f"{group_id[:8]}-item", group_id, "測試品", "100", "")]
        for group_id in groups
    }
    buyers = [
        {"name": "買家甲", "charge": "11", "paidSum": "0", "remaining": "11"},
        {"name": "買家乙", "charge": "22", "paidSum": "0", "remaining": "22"},
    ]
    return groups, items, buyers


def detail_for(group_id, buyer, charge):
    return {
        "groupBuy": base_group(group_id),
        "orders": [
            {
                "id": f"{group_id[:8]}-order",
                "buyerName": buyer,
                "isSelf": False,
                "items": [item(f"{group_id[:8]}-item", "測試品", "100", "")],
                "payments": [],
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": f"{group_id[:8]}-order",
                    "goodsCharge": charge,
                    "feeCharge": "0",
                    "charge": charge,
                    "paidSum": "0",
                    "remaining": charge,
                }
            ]
        },
    }


def site_root(tmp_path: Path, allow_ids: list[str]) -> Path:
    (tmp_path / "sync").mkdir()
    (tmp_path / "sync" / "allowlist.json").write_text(
        json.dumps({"include": allow_ids}),
        encoding="utf-8",
    )
    (tmp_path / "sync" / "billing_groups.json").write_text(
        json.dumps({"include": [allow_ids[0]], "empty": "月中暫無款項請款"}),
        encoding="utf-8",
    )
    return tmp_path
