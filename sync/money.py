"""金額與日期。結算整數以來源為準，不做另一套四捨五入。"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sync.errors import SchemaError

_TAIPEI = ZoneInfo("Asia/Taipei")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 只有日期，或帶時間的 ISO。時間再換算成台北的日曆日。
_ISO_DATE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[T ](?P<hms>\d{2}:\d{2}:\d{2})(?P<frac>\.\d+)?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?)?$"
)
# JavaScript Date.toString()，例如 Sun Nov 08 2026 20:08:12 GMT+0800 (Taiwan Standard Time)
_JS_DATE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"(?P<day>\d{1,2}) (?P<year>\d{4}) "
    r"(?P<hms>\d{2}:\d{2}:\d{2})(?:\.\d+)? "
    r"GMT(?P<tz>[+-]\d{2}:?\d{2})"
    r"(?: \([^)]*\))?$"
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}


def as_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise SchemaError("金額格式不正確")
    try:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, str):
            return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise SchemaError("金額格式不正確") from None
    raise SchemaError("金額格式不正確")


def plain_number(value: object) -> int | float:
    number = as_decimal(value)
    integral = number.to_integral_value()
    if number == integral:
        return int(integral)
    quantized = number.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP).normalize()
    return float(format(quantized, "f"))


def half_up_int(value: object) -> int:
    """顯示用的商品／費用拆分。應收總額不要用這個函式重算。"""
    return int(as_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def source_int(value: object, label: str) -> int:
    """來源已四捨五入的台幣整數。帶小數就中止，避免再算一次。"""
    number = as_decimal(value)
    if number != number.to_integral_value():
        raise SchemaError(f"{label}不是來源整數台幣")
    return int(number)


def norm_amount(value: object) -> str:
    return format(as_decimal(value).normalize(), "f")


def public_date(value: object, field: str) -> str:
    """把來源日期收成台北日曆日。無法辨識就中止，錯誤只帶欄位名稱。"""
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise SchemaError(f"日期格式無法辨識（{field}）")
    text = value.strip()
    iso = _ISO_DATE.fullmatch(text)
    if iso:
        if iso.group("hms") is None:
            return _calendar_day(iso.group("date"), field)
        return _taipei_day(iso.group("date"), iso.group("hms"), iso.group("frac"), iso.group("tz"), field)
    js = _JS_DATE.fullmatch(text)
    if js:
        date = f"{int(js.group('year')):04d}-{_MONTHS[js.group('mon')]:02d}-{int(js.group('day')):02d}"
        return _taipei_day(date, js.group("hms"), None, js.group("tz"), field)
    raise SchemaError(f"日期格式無法辨識（{field}）")


def _calendar_day(date: str, field: str) -> str:
    try:
        return datetime.strptime(date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise SchemaError(f"日期格式無法辨識（{field}）") from None


def _taipei_day(date: str, hms: str, frac: str | None, tz: str | None, field: str) -> str:
    try:
        moment = datetime.fromisoformat(f"{date}T{hms}{frac or ''}{_offset(tz)}")
    except ValueError:
        raise SchemaError(f"日期格式無法辨識（{field}）") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_TAIPEI)
    return moment.astimezone(_TAIPEI).date().isoformat()


def _offset(tz: str | None) -> str:
    if tz is None:
        return ""
    if tz == "Z":
        return "+00:00"
    if re.fullmatch(r"[+-]\d{4}", tz):
        return f"{tz[:3]}:{tz[3:]}"
    return tz


def reject_email(value: object) -> str:
    text = "" if value is None else str(value)
    if _EMAIL.search(text):
        raise SchemaError("公開欄位含有電子郵件，已中止")
    return text
