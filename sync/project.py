"""把允許清單內的團購收成網站既有的公開形狀。

公開物件只保留 index.html 已經在用的欄位。成本匯率、利潤、成員、
支付、訂單備註與品項備註都不會寫進結果。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from sync.errors import SchemaError
from sync.images import image_ref
from sync.money import half_up_int, norm_amount, plain_number, public_date, reject_email, source_int

GROUP_STATUSES = {"open", "closed", "arrived", "settled"}
ITEM_STATUSES = {"recorded", "ordered", "shipped", "packing", "delivered", "completed"}
CURRENCY_LABEL = {"JPY": "日幣", "CNY": "人民幣", "TWD": "台幣", "NTD": "台幣"}
_ID = re.compile(r"^[0-9a-f]{32}$")
_CURRENCY = re.compile(r"^[A-Z]{3,4}$")

TOP_KEYS = {"fetchedAt", "gbs", "buyers", "billing"}
GROUP_KEYS = {"id", "n", "src", "cur", "st", "dt", "img", "url", "rate", "fees", "o"}
ORDER_KEYS = {"b", "self", "gc", "fc", "charge", "sv", "paid", "rem", "it", "pay"}
BUYER_KEYS = {"n", "gc", "q", "charge", "paid", "rem", "off", "offs", "lines"}
BILLING_KEYS = {"items", "empty", "buyers"}
BILLING_LINE_KEYS = {"name", "amount", "note"}
BILLING_BUYER_KEYS = {"name", "total", "items"}


@dataclass(frozen=True)
class BillingEntry:
    id: str
    buyers: tuple[str, ...] | None = None


def parse_billing_include(raw_ids, *, allow_empty: bool = True) -> list[BillingEntry]:
    if not isinstance(raw_ids, list):
        raise SchemaError("請款預告格式不正確")
    if not raw_ids and not allow_empty:
        raise SchemaError("請款預告沒有 id")
    entries: list[BillingEntry] = []
    seen: set[str] = set()
    for raw in raw_ids:
        group_id, buyers = _billing_entry_parts(raw)
        if not isinstance(group_id, str) or not _ID.fullmatch(group_id):
            raise SchemaError("請款預告有不正確的 id")
        if group_id in seen:
            raise SchemaError("請款預告有重複 id")
        seen.add(group_id)
        entries.append(BillingEntry(group_id, buyers))
    return entries


def _billing_entry_parts(raw) -> tuple[str, tuple[str, ...] | None]:
    if isinstance(raw, BillingEntry):
        return raw.id, _normalize_billing_buyers(raw.buyers)
    if isinstance(raw, str):
        return raw, None
    if isinstance(raw, dict):
        if set(raw) - {"id", "buyers"}:
            raise SchemaError("請款預告有不支援的欄位")
        buyers = None if "buyers" not in raw else _normalize_billing_buyers(raw["buyers"])
        return raw.get("id"), buyers
    raise SchemaError("請款預告格式不正確")


def _normalize_billing_buyers(names) -> tuple[str, ...] | None:
    if names is None:
        return None
    if not isinstance(names, (list, tuple)) or not names:
        raise SchemaError("請款預告的買家清單不正確")
    seen: set[str] = set()
    cleaned: list[str] = []
    for name in names:
        if not isinstance(name, str) or not name or name != name.strip():
            raise SchemaError("請款預告的買家名稱不正確")
        if name in seen:
            raise SchemaError("請款預告有重複的買家")
        seen.add(name)
        cleaned.append(name)
    return tuple(cleaned)


def parse_offset_notes(raw) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, (list, tuple, set, frozenset)):
        raise SchemaError("抵扣備註清單格式不正確")
    notes: list[str] = []
    seen: set[str] = set()
    for note in raw:
        if not isinstance(note, str) or not note or note != note.strip():
            raise SchemaError("抵扣備註不正確")
        if note in seen:
            raise SchemaError("抵扣備註重複")
        seen.add(note)
        notes.append(note)
    return frozenset(notes)


def parse_buyer_aliases(raw) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SchemaError("買家別名格式不正確")
    aliases: dict[str, str] = {}
    for source, target in raw.items():
        if not isinstance(source, str) or not source or source != source.strip():
            raise SchemaError("買家別名不正確")
        if not isinstance(target, str) or not target or target != target.strip():
            raise SchemaError("買家別名不正確")
        if source == target:
            raise SchemaError("買家別名不能指向自己")
        aliases[source] = target
    flat: dict[str, str] = {}
    for source in aliases:
        current = source
        seen: set[str] = set()
        while current in aliases:
            if current in seen:
                raise SchemaError("買家別名有循環")
            seen.add(current)
            current = aliases[current]
        flat[source] = current
    return flat


def canonical_buyer(name: str, aliases: dict[str, str] | None = None) -> str:
    if not aliases:
        return name
    return aliases.get(name, name)


def project_publication(
    details: list[dict],
    items_by_group: dict[str, list[dict]],
    summary_buyers: list[dict],
    *,
    previous: dict | None,
    billing_ids: list[str],
    fetched_at: str,
    empty_text: str,
    buyer_aliases: dict[str, str] | None = None,
    offset_notes=None,
) -> tuple[dict, dict[str, str]]:
    aliases = parse_buyer_aliases(buyer_aliases)
    notes = parse_offset_notes(offset_notes)
    offsets = _offset_index(previous, notes)
    images: dict[str, str] = {}
    groups = []
    for detail in details:
        group = _project_group(detail, items_by_group, offsets, images)
        groups.append(group)
    groups.sort(key=lambda group: group["id"])
    groups.sort(key=lambda group: group["dt"], reverse=True)
    buyers = _build_buyers(groups, aliases)
    _assert_summary(buyers, summary_buyers, aliases)
    billing = _build_billing(groups, parse_billing_include(list(billing_ids)), empty_text, aliases)
    public = {
        "fetchedAt": fetched_at,
        "gbs": groups,
        "buyers": buyers,
        "billing": billing,
    }
    validate_public(public)
    return public, images


def validate_public(public: dict) -> None:
    if set(public) != TOP_KEYS:
        raise SchemaError("公開資料的頂層欄位與網站不一致")
    if not isinstance(public["gbs"], list) or not public["gbs"]:
        raise SchemaError("公開團購是空的")
    seen = set()
    for group in public["gbs"]:
        if set(group) != GROUP_KEYS:
            raise SchemaError("團購公開欄位與網站不一致")
        if not _ID.fullmatch(group["id"]) or group["id"] in seen:
            raise SchemaError("團購 id 不正確或重複")
        seen.add(group["id"])
        if group["st"] not in GROUP_STATUSES:
            raise SchemaError("團購狀態不正確")
        for fee in group["fees"]:
            if not isinstance(fee, list) or len(fee) != 3 or fee[2] not in ("foreign", "local"):
                raise SchemaError("費用公開欄位與網站不一致")
        for order in group["o"]:
            if set(order) != ORDER_KEYS or order["self"] not in (0, 1):
                raise SchemaError("訂單公開欄位與網站不一致")
            for item in order["it"]:
                if not isinstance(item, list) or len(item) != 6 or item[3] not in ITEM_STATUSES:
                    raise SchemaError("品項公開欄位與網站不一致")
            for payment in order["pay"]:
                if not isinstance(payment, list) or len(payment) != 4 or payment[3] not in (0, 1):
                    raise SchemaError("收款公開欄位與網站不一致")
            if order["self"] and (order["charge"] or order["paid"] or order["rem"] or order["pay"]):
                raise SchemaError("團主自留單不應公開應收或收款")
    for buyer in public["buyers"]:
        if set(buyer) != BUYER_KEYS:
            raise SchemaError("買家公開欄位與網站不一致")
    billing = public["billing"]
    if set(billing) != BILLING_KEYS:
        raise SchemaError("請款預告欄位與網站不一致")
    for line in billing["items"]:
        if set(line) != BILLING_LINE_KEYS:
            raise SchemaError("請款預告欄位與網站不一致")
    for buyer in billing["buyers"]:
        if set(buyer) != BILLING_BUYER_KEYS:
            raise SchemaError("請款預告欄位與網站不一致")
        for line in buyer["items"]:
            if set(line) != BILLING_LINE_KEYS:
                raise SchemaError("請款預告欄位與網站不一致")


def content_signature(public: dict | None) -> str | None:
    if public is None:
        return None
    body = {key: value for key, value in public.items() if key != "fetchedAt"}
    import json

    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _project_group(detail: dict, items_by_group: dict[str, list[dict]], offsets, images: dict[str, str]) -> dict:
    try:
        group = detail["groupBuy"]
        orders = detail["orders"]
        settlement_rows = detail["settlement"]["orders"]
    except (KeyError, TypeError):
        raise SchemaError("團購明細格式無法辨識") from None
    group_id = str(group.get("id") or "")
    if not _ID.fullmatch(group_id):
        raise SchemaError("團購 id 格式不正確")
    listed = items_by_group.get(group_id)
    if listed is None:
        raise SchemaError("缺少品項交叉核對")
    _assert_items(orders, listed, group_id)
    settlements = {}
    for row in settlement_rows:
        try:
            settlements[str(row["orderId"])] = row
        except (KeyError, TypeError):
            raise SchemaError("結算格式無法辨識") from None
    if set(settlements) != {str(order.get("id")) for order in orders}:
        raise SchemaError("結算與訂單沒有對上")

    fees = []
    for fee in detail.get("fees") or []:
        if fee.get("absorb") is True:
            continue
        currency = fee.get("currency")
        if currency not in ("foreign", "local"):
            raise SchemaError("費用幣別不正確")
        name = reject_email(fee.get("name")).strip()
        if not name:
            raise SchemaError("費用名稱是空的")
        fees.append([name, plain_number(fee.get("amount")), currency])

    projected_orders = []
    for order in orders:
        row = settlements[str(order.get("id"))]
        buyer = reject_email(order.get("buyerName")).strip()
        if not buyer:
            raise SchemaError("買家名稱是空的")
        items = [_project_item(item, images) for item in order.get("items") or []]
        if order.get("isSelf") is True:
            projected_orders.append(
                {
                    "b": buyer,
                    "self": 1,
                    "gc": 0,
                    "fc": 0,
                    "charge": 0,
                    "sv": source_int(row.get("charge"), "團主結算"),
                    "paid": 0,
                    "rem": 0,
                    "it": items,
                    "pay": [],
                }
            )
            continue
        payments = []
        for payment in order.get("payments") or []:
            amount = plain_number(payment.get("amount"))
            if amount <= 0:
                raise SchemaError("收款金額必須是正數")
            paid_at = public_date(payment.get("paidAt"), "paidAt")
            note = reject_email(payment.get("note"))
            flag = offsets(group_id, buyer, amount, paid_at, note)
            payments.append([amount, paid_at, note, flag])
        payments.sort(key=lambda payment: (payment[1], norm_amount(payment[0]), payment[2]))
        projected_orders.append(
            {
                "b": buyer,
                "self": 0,
                "gc": half_up_int(row.get("goodsCharge") or 0),
                "fc": half_up_int(row.get("feeCharge") or 0),
                "charge": source_int(row.get("charge"), "應收"),
                "sv": 0,
                "paid": source_int(row.get("paidSum"), "已收"),
                "rem": source_int(row.get("remaining"), "未收"),
                "it": items,
                "pay": payments,
            }
        )
    projected_orders.sort(key=lambda order: (order["self"], order["b"]))

    name = reject_email(group.get("name")).strip()
    if not name:
        raise SchemaError("團名是空的")
    status = group.get("status")
    if status not in GROUP_STATUSES:
        raise SchemaError("團購狀態不正確")
    started = public_date(group.get("startedAt"), "startedAt")
    if not started:
        raise SchemaError("缺少成立日期")
    currency = str(group.get("currency") or "").strip().upper() or "TWD"
    if not _CURRENCY.fullmatch(currency):
        raise SchemaError("幣別格式不正確")
    rate = None if group.get("chargeRate") is None else plain_number(group.get("chargeRate"))
    return {
        "id": group_id,
        "n": name,
        "src": reject_email(group.get("source") or ""),
        "cur": currency,
        "st": status,
        "dt": started,
        "img": _remember_image(group.get("image"), images),
        "url": _public_url(group.get("url")),
        "rate": rate,
        "fees": fees,
        "o": projected_orders,
    }


def _project_item(item: dict, images: dict[str, str]) -> list:
    status = item.get("status")
    if status not in ITEM_STATUSES:
        raise SchemaError("品項狀態不正確")
    try:
        quantity = int(item["quantity"])
        unit_price = plain_number(item.get("unitPrice") or 0)
    except (KeyError, TypeError, ValueError):
        raise SchemaError("品項數量或單價不正確") from None
    if quantity <= 0:
        raise SchemaError("品項數量不正確")
    name = reject_email(item.get("name")).strip()
    if not name:
        raise SchemaError("品項名稱是空的")
    shipping = reject_email(item.get("shippingNumber") or "")
    return [name, unit_price, quantity, status, shipping, _remember_image(item.get("image"), images)]


def _remember_image(value: object, images: dict[str, str]) -> str:
    key, url = image_ref(value)
    if not key:
        return ""
    if not url:
        raise SchemaError("圖片缺少來源位置")
    previous = images.get(key)
    if previous is not None and previous != url:
        raise SchemaError("同一張公開圖片對到兩個來源")
    images[key] = url
    return key


def _public_url(value: object) -> str:
    if value is None or value == "":
        return ""
    text = str(value).strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SchemaError("商品連結格式不正確")
    if parts.username or parts.password:
        raise SchemaError("商品連結含有認證資訊")
    return text


def _assert_items(orders: list[dict], listed: list[dict], group_id: str) -> None:
    detail = {}
    for order in orders:
        for item in order.get("items") or []:
            item_id = str(item.get("id") or "")
            if not item_id or item_id in detail:
                raise SchemaError("品項 id 不正確或重複")
            detail[item_id] = item
    found = {}
    for item in listed:
        other_group = item.get("groupBuyId")
        if other_group and str(other_group) != group_id:
            raise SchemaError("品項回應含有這次沒有指定的團購")
        item_id = str(item.get("id") or "")
        if not item_id or item_id in found:
            raise SchemaError("品項清單 id 不正確或重複")
        found[item_id] = item
    if set(detail) != set(found):
        raise SchemaError("品項清單與團購明細不一致")
    for item_id, item in detail.items():
        other = found[item_id]
        if str(other.get("status") or "") != str(item.get("status") or ""):
            raise SchemaError("品項狀態與 /items 不一致")
        if str(other.get("shippingNumber") or "") != str(item.get("shippingNumber") or ""):
            raise SchemaError("寄件編號與 /items 不一致")
        if image_ref(other.get("image"))[0] != image_ref(item.get("image"))[0]:
            raise SchemaError("品項圖片與 /items 不一致")


def _offset_index(previous: dict | None, offset_notes: frozenset[str] | None = None) -> Callable:
    notes = offset_notes or frozenset()
    flags: dict[tuple, set[int]] = {}
    for group in (previous or {}).get("gbs") or []:
        for order in group.get("o") or []:
            for payment in order.get("pay") or []:
                if not isinstance(payment, list) or len(payment) < 4:
                    continue
                key = (group.get("id"), order.get("b"), norm_amount(payment[0]), payment[1], payment[2])
                flags.setdefault(key, set()).add(int(payment[3]))

    def lookup(group_id: str, buyer: str, amount, paid_at: str, note: str) -> int:
        found = flags.get((group_id, buyer, norm_amount(amount), paid_at, note))
        if found == {1} or note in notes:
            return 1
        return 0

    return lookup


def _build_buyers(groups: list[dict], aliases: dict[str, str] | None = None) -> list[dict]:
    chronological = sorted(groups, key=lambda group: (group["dt"], group["id"]))
    aggregated: dict[str, dict] = {}
    for group in chronological:
        for order in group["o"]:
            if order["self"]:
                continue
            display = canonical_buyer(order["b"], aliases)
            buyer = aggregated.setdefault(
                display,
                {
                    "n": display,
                    "gc": 0,
                    "q": 0,
                    "charge": 0,
                    "paid": 0,
                    "rem": 0,
                    "off": 0,
                    "offs": [],
                    "lines": [],
                },
            )
            buyer["gc"] += 1
            buyer["q"] += sum(item[2] for item in order["it"])
            buyer["charge"] += order["charge"]
            buyer["paid"] += order["paid"]
            buyer["rem"] += order["rem"]
            if order["rem"] > 0:
                buyer["lines"].append([group["n"], group["st"], order["charge"], order["rem"]])
            for payment in order["pay"]:
                if payment[3]:
                    buyer["off"] += payment[0]
                    buyer["offs"].append([group["n"], payment[1], payment[0], payment[2]])
    return [aggregated[name] for name in sorted(aggregated)]


def _assert_summary(
    buyers: list[dict],
    summary_buyers: list[dict],
    aliases: dict[str, str] | None = None,
) -> None:
    calculated = {buyer["n"]: buyer for buyer in buyers}
    folded: dict[str, dict[str, int]] = {}
    for row in summary_buyers:
        if row.get("isSelfOnly") is True:
            continue
        try:
            name = canonical_buyer(str(row["name"]), aliases)
            charge = source_int(row["charge"], "買家總覽應收")
            paid = source_int(row["paidSum"], "買家總覽已收")
            remaining = source_int(row["remaining"], "買家總覽未收")
        except (KeyError, TypeError):
            raise SchemaError("買家總覽格式無法辨識") from None
        totals = folded.setdefault(name, {"charge": 0, "paid": 0, "remaining": 0})
        totals["charge"] += charge
        totals["paid"] += paid
        totals["remaining"] += remaining
    seen = set()
    for name, totals in folded.items():
        buyer = calculated.get(name)
        if buyer is None:
            if totals["charge"] == 0 and totals["paid"] == 0 and totals["remaining"] == 0:
                continue
            raise SchemaError("買家總覽含有這次公開範圍以外的應收")
        if buyer["charge"] != totals["charge"] or buyer["paid"] != totals["paid"] or buyer["rem"] != totals["remaining"]:
            raise SchemaError("買家總覽與來源結算整數不一致")
        seen.add(name)
    if set(calculated) - seen:
        raise SchemaError("買家總覽少了已投影的買家")


def _build_billing(
    groups: list[dict],
    billing_entries: list[BillingEntry],
    empty_text: str,
    aliases: dict[str, str] | None = None,
) -> dict:
    by_id = {group["id"]: group for group in groups}
    items = []
    buyers: dict[str, dict] = {}
    for entry in billing_entries:
        group = by_id.get(entry.id)
        if group is None:
            raise SchemaError("請款預告的團不在這次公開投影")
        selected = _billing_orders(group, entry.buyers)
        remaining = sum(order["rem"] for order in selected)
        if remaining <= 0:
            continue
        charge = sum(order["charge"] for order in selected)
        paid = sum(order["paid"] for order in selected)
        items.append({"name": group["n"], "amount": remaining, "note": _billing_note(group, charge, paid, selected)})
        for order in selected:
            if order["rem"] <= 0:
                continue
            display = canonical_buyer(order["b"], aliases)
            buyer = buyers.setdefault(display, {"name": display, "total": 0, "items": []})
            buyer["total"] += order["rem"]
            buyer["items"].append({"name": group["n"], "amount": order["rem"], "note": ""})
    ordered = sorted(buyers.values(), key=lambda buyer: (-buyer["total"], buyer["name"]))
    return {"items": items, "empty": empty_text, "buyers": ordered}


def _billing_orders(group: dict, allowed: tuple[str, ...] | None) -> list[dict]:
    orders = group["o"]
    if allowed is None:
        return [order for order in orders if not order["self"]]
    names = {order["b"] for order in orders}
    missing = [name for name in allowed if name not in names]
    if missing:
        raise SchemaError("請款預告指定的買家不在團內")
    allowed_set = set(allowed)
    return [order for order in orders if order["b"] in allowed_set and not order["self"]]


def _billing_note(group: dict, charge: int, paid: int, orders: list[dict]) -> str:
    if group["cur"] in ("TWD", "NTD"):
        return f"應收 {charge:,}，已收 {paid:,}" if paid else ""
    foreign = 0
    for order in orders:
        for item in order["it"]:
            foreign += item[1] * item[2]
    label = CURRENCY_LABEL.get(group["cur"], group["cur"])
    note = f"{label} ¥{foreign:,.0f}" if float(foreign).is_integer() else f"{label} ¥{foreign}"
    if paid:
        note += f"・應收 {charge:,}，已收 {paid:,}"
    return note
