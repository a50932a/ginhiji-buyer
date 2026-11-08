"""金額與日期。結算整數以來源為準，不做另一套四捨五入。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sync.errors import SchemaError

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


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


def date_prefix(value: object) -> str:
    if value is None or value == "":
        return ""
    text = str(value).strip()
    match = _DATE.match(text)
    if not match:
        raise SchemaError("日期格式無法辨識")
    return match.group(0)


def reject_email(value: object) -> str:
    text = "" if value is None else str(value)
    if _EMAIL.search(text):
        raise SchemaError("公開欄位含有電子郵件，已中止")
    return text
