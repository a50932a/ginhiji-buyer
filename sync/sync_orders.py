"""同步允許清單內的團購到 data/public.json。

失敗、授權錯誤或內容無法安全投影時，不改寫上一筆公開資料。
內容相同則不寫檔。這個程式只讀來源，不會對訂單 API 送出寫入。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sync.client import OrdersClient
from sync.errors import AuthError, MissingImage, MissingToken, SchemaError, SourceError, SyncError
from sync.images import jpeg_variants, sha256_bytes
from sync.project import content_signature, parse_billing_include, project_publication, validate_public

_ID = re.compile(r"^[0-9a-f]{32}$")
_TAIPEI = ZoneInfo("Asia/Taipei")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同步買家網站的公開訂單投影")
    parser.add_argument("--root", default=".", help="網站倉庫根目錄")
    parser.add_argument("--dry-run", action="store_true", help="只讀來源並檢查，不寫檔")
    parser.add_argument(
        "--projection",
        help="審查過的離線投影檔。正式更新請省略，改由 ORDERS_API_TOKEN 讀來源",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    source = None
    try:
        if args.projection:
            source = ProjectionFile(Path(args.projection))
        else:
            token = os.environ.get("ORDERS_API_TOKEN", "")
            if not token.strip():
                print("缺少環境變數 ORDERS_API_TOKEN，沒有改寫公開資料。", file=sys.stderr)
                return 2
            source = OrdersClient(token)
        result = run_sync(root, source, dry_run=args.dry_run)
    except AuthError:
        print("來源拒絕授權，已保留上一筆公開資料。", file=sys.stderr)
        return 3
    except MissingToken:
        print("缺少環境變數 ORDERS_API_TOKEN，沒有改寫公開資料。", file=sys.stderr)
        return 2
    except SyncError as exc:
        print(f"同步中止，已保留上一筆公開資料：{exc}", file=sys.stderr)
        return 1
    finally:
        close = getattr(source, "close", None)
        if close:
            close()
    print(result)
    return 0


def run_sync(root: Path, source, *, now: datetime | None = None, dry_run: bool = False) -> str:
    allowlist = load_id_list(root / "sync" / "allowlist.json")
    billing_file, billing_entries = load_billing_file(root / "sync" / "billing_groups.json")
    billing_ids = [entry.id for entry in billing_entries]
    if not set(billing_ids) <= set(allowlist):
        raise SchemaError("請款預告含有未允許的團")
    empty_text = str(billing_file.get("empty") or "月中暫無款項請款")
    previous = _read_public(root / "data" / "public.json")
    previous_ids = {group["id"] for group in previous["gbs"]} if previous else set()

    listed_ids = []
    seen = set()
    for row in source.list_groups():
        group_id = str(row.get("id") or "")
        if not _ID.fullmatch(group_id):
            raise SchemaError("來源團購 id 格式不正確")
        if group_id in seen:
            continue
        seen.add(group_id)
        listed_ids.append(group_id)
    listed = set(listed_ids)
    if any(group_id in previous_ids and group_id not in listed for group_id in allowlist):
        raise SchemaError("先前已公開的團購不在來源清單")
    fetch_ids = [group_id for group_id in allowlist if group_id in listed]
    if not fetch_ids:
        raise SchemaError("允許清單裡沒有任何來源團購")
    pending = [group_id for group_id in allowlist if group_id not in listed and group_id not in previous_ids]
    if pending:
        print(f"允許清單有 {len(pending)} 筆尚未出現在來源，這次沒有新增")

    details = []
    items_by_group = {}
    for group_id in fetch_ids:
        detail = source.get_group(group_id)
        for private_key in ("members", "payouts", "role"):
            if isinstance(detail, dict):
                detail.pop(private_key, None)
        items_by_group[group_id] = _guard_items(source.get_items(group_id), group_id)
        details.append(detail)
    summary = source.buyers_summary(fetch_ids)
    moment = now or datetime.now(_TAIPEI)
    fetched_at = moment.strftime("%Y-%m-%d %H:%M")
    public, images = project_publication(
        details,
        items_by_group,
        summary,
        previous=previous,
        billing_ids=billing_entries,
        fetched_at=(previous or {}).get("fetchedAt") or fetched_at,
        empty_text=empty_text,
    )
    if content_signature(public) != content_signature(previous):
        public["fetchedAt"] = fetched_at
    validate_public(public)

    staged, cache, cache_changed = _prepare_images(root, source, images)
    json_changed = content_signature(public) != content_signature(previous)
    if not json_changed and not staged and not cache_changed:
        print(f"公開團購 {len(public['gbs'])} 筆，內容沒有變化")
        return "noop"
    print(f"公開團購 {len(public['gbs'])} 筆，待寫入圖片 {len(staged)} 張")
    if dry_run:
        return "dry-run"
    _commit(root, public if json_changed else None, staged, cache if cache_changed else None)
    return "updated"


def load_billing_file(path: Path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_ids = payload["include"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        raise SchemaError(f"無法讀取 {path.name}") from None
    return payload, parse_billing_include(raw_ids, allow_empty=False)


def load_id_list(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_ids = payload["include"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        raise SchemaError(f"無法讀取 {path.name}") from None
    if not isinstance(raw_ids, list) or not raw_ids:
        raise SchemaError(f"{path.name} 沒有 id")
    ids = []
    seen = set()
    for group_id in raw_ids:
        if not isinstance(group_id, str) or not _ID.fullmatch(group_id):
            raise SchemaError(f"{path.name} 有不正確的 id")
        if group_id in seen:
            raise SchemaError(f"{path.name} 有重複 id")
        seen.add(group_id)
        ids.append(group_id)
    return ids


class ProjectionFile:
    """讀取審查過的投影。檔內若還有成本、利潤、成員或支付欄位就拒絕。"""

    _DENIED = {
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

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise SchemaError("找不到投影檔")
        if path.stat().st_size > 20_000_000:
            raise SchemaError("投影檔過大")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), parse_float=str)
        except (OSError, json.JSONDecodeError):
            raise SchemaError("投影檔不是 JSON") from None
        _reject_denied_keys(payload, self._DENIED)
        try:
            self._groups = payload["groups"]
            self._items = payload["items"]
            self._buyers = payload["buyers"]
        except (KeyError, TypeError):
            raise SchemaError("投影檔格式無法辨識") from None
        self._by_id = {}
        for detail in self._groups:
            try:
                group_id = str(detail["groupBuy"]["id"])
            except (KeyError, TypeError):
                raise SchemaError("投影檔缺少團購 id") from None
            self._by_id[group_id] = detail

    def list_groups(self) -> list[dict]:
        return [{"id": group_id} for group_id in self._by_id]

    def get_group(self, group_id: str) -> dict:
        try:
            return self._by_id[group_id]
        except KeyError:
            raise SourceError("投影檔缺少團購") from None

    def get_items(self, group_id: str) -> list[dict]:
        try:
            items = self._items[group_id]
        except (KeyError, TypeError):
            raise SchemaError("投影檔缺少品項") from None
        if not isinstance(items, list):
            raise SchemaError("投影檔品項格式不正確")
        return items

    def buyers_summary(self, group_ids: list[str]) -> list[dict]:
        if not isinstance(self._buyers, list):
            raise SchemaError("投影檔買家總覽格式不正確")
        return self._buyers

    def stat_image(self, url: str) -> str | None:
        return None

    def get_image(self, url: str) -> tuple[bytes, str | None]:
        raise SourceError("離線投影不含圖片位元組")

    def close(self) -> None:
        return None


def _reject_denied_keys(value, denied: set[str]) -> None:
    if isinstance(value, dict):
        found = denied.intersection(value)
        if found:
            raise SchemaError("投影檔含有不公開欄位")
        for child in value.values():
            _reject_denied_keys(child, denied)
    elif isinstance(value, list):
        for child in value:
            _reject_denied_keys(child, denied)


def _read_public(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise SchemaError("現有公開資料無法讀取，已停止以免覆蓋") from None
    validate_public(payload)
    return payload


def _guard_items(items: list[dict], group_id: str) -> list[dict]:
    guarded = []
    for item in items:
        if not isinstance(item, dict):
            raise SchemaError("品項清單格式無法辨識")
        other = item.get("groupBuyId")
        if other and str(other) != group_id:
            raise SchemaError("品項回應含有這次沒有指定的團購")
        guarded.append(item)
    return guarded


def _prepare_images(root: Path, source, images: dict[str, str]):
    cache_path = root / "data" / "image-cache.json"
    cache = {"images": {}}
    if cache_path.exists():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded.get("images"), dict):
                cache = loaded
        except (OSError, json.JSONDecodeError):
            raise SchemaError("圖片快取無法讀取") from None
    known = cache.get("images") if isinstance(cache.get("images"), dict) else {}
    updated: dict[str, dict] = {}
    staged: dict[str, tuple[bytes, bytes, str | None]] = {}
    for key, url in sorted(images.items()):
        large = root / "img" / "l" / f"{key}.jpg"
        thumb = root / "img" / "t" / f"{key}.jpg"
        have_files = large.is_file() and thumb.is_file()
        entry = known.get(key) if isinstance(known.get(key), dict) else {}
        cached_etag = entry.get("etag") if isinstance(entry, dict) else None
        cached_sha = entry.get("sha256") if isinstance(entry, dict) else None
        local_sha = sha256_bytes(large.read_bytes()) if have_files else None
        needs_download = not have_files or (cached_sha is not None and local_sha != cached_sha)
        try:
            if needs_download:
                pass
            elif cached_etag:
                remote = source.stat_image(url)
                if remote in (None, cached_etag):
                    updated[key] = {"etag": cached_etag, "sha256": local_sha}
                    continue
                needs_download = True
            else:
                remote = source.stat_image(url)
                if remote:
                    updated[key] = {"etag": remote, "sha256": local_sha}
                elif local_sha:
                    updated[key] = {"etag": None, "sha256": local_sha}
                continue
        except MissingImage:
            if have_files and not needs_download:
                if local_sha:
                    updated[key] = {"etag": cached_etag, "sha256": local_sha}
                continue
            raise
        except SyncError:
            # 既有圖片的 HEAD 被拒或暫時失敗時，保留檔案，避免整次公開更新中止。
            # 缺圖或必須重抓時仍往下走，失敗就中止且不寫公開檔。
            if have_files and not needs_download:
                if local_sha:
                    updated[key] = {"etag": cached_etag, "sha256": local_sha}
                continue
            raise
        if not needs_download:
            continue
        try:
            body, etag = source.get_image(url)
        except MissingImage:
            if have_files:
                if local_sha:
                    updated[key] = {"etag": cached_etag, "sha256": local_sha}
                continue
            raise
        large_bytes, thumb_bytes = jpeg_variants(body)
        staged[key] = (large_bytes, thumb_bytes, etag)
        updated[key] = {"etag": etag, "sha256": sha256_bytes(large_bytes)}
    next_cache = {"images": updated}
    return staged, next_cache, next_cache != {"images": known}


def _commit(root: Path, public: dict | None, staged: dict, cache: dict | None) -> None:
    writes: list[tuple[Path, bytes]] = []
    if public is not None:
        writes.append((root / "data" / "public.json", _pretty(public)))
    if cache is not None:
        writes.append((root / "data" / "image-cache.json", _pretty(cache)))
    for key, (large, thumb, _etag) in staged.items():
        writes.append((root / "img" / "l" / f"{key}.jpg", large))
        writes.append((root / "img" / "t" / f"{key}.jpg", thumb))
    temps: list[tuple[Path, Path]] = []
    try:
        for destination, payload in writes:
            destination.parent.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
            temporary = Path(name)
            temps.append((temporary, destination))
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        for temporary, destination in temps:
            os.replace(temporary, destination)
    except Exception:
        for temporary, _destination in temps:
            temporary.unlink(missing_ok=True)
        raise
    finally:
        for temporary, destination in temps:
            if temporary.exists() and temporary.resolve() != destination.resolve():
                temporary.unlink(missing_ok=True)


def _pretty(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


if __name__ == "__main__":
    sys.exit(main())
