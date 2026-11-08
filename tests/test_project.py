"""公開投影測試。這裡的訂單是測試資料，不是正式團購。"""

from __future__ import annotations

import json

import pytest

from sync.errors import SchemaError
from sync.money import half_up_int
from sync.project import project_publication


def test_half_up_is_not_bankers_rounding():
    assert half_up_int("2.5") == 3
    assert half_up_int("-1.5") == -2


def test_publication_uses_source_rounded_twd_and_strips_private_fields():
    # 3478 * 0.23 = 799.94。直接砍掉小數會變成 799，來源結算是 800。
    # 3148 * 0.23 = 724.04，來源結算是 724。
    group_id = "a" * 32
    detail = {
        "groupBuy": {
            "id": group_id,
            "name": "測試繪本",
            "source": "測試商店",
            "currency": "JPY",
            "status": "closed",
            "startedAt": "2026-11-07",
            "url": "https://example.com/item",
            "image": "/api/images/abc123def456",
            "chargeRate": "0.23",
            "costRate": "0.187654",
            "note": "內部團購備註",
        },
        "orders": [
            {
                "id": "order-a",
                "buyerName": "買家甲",
                "isSelf": False,
                "note": "內部備註勿公開",
                "items": [
                    item("item-a1", "測試繪本", "2673", "/api/images/abc123def456"),
                    item("item-a2", "測試周邊", "330", "/api/images/fff123def456"),
                ],
                "payments": [],
            },
            {
                "id": "order-b",
                "buyerName": "買家乙",
                "isSelf": False,
                "items": [item("item-b1", "測試繪本", "2673", "/api/images/abc123def456")],
                "payments": [{"amount": "100", "paidAt": "2026-11-08T01:02:03Z", "note": "測試轉帳"}],
            },
            {
                "id": "order-self",
                "buyerName": "團主",
                "isSelf": True,
                "items": [item("item-s", "測試自留", "500", "")],
                "payments": [{"amount": "1", "paidAt": "2026-11-08", "note": "不應公開"}],
            },
        ],
        "fees": [
            {"name": "測試運費", "amount": "950", "currency": "foreign", "absorb": False},
            {"name": "自行吸收回饋", "amount": "-30", "currency": "local", "absorb": True},
        ],
        "settlement": {
            "profit": 654321,
            "costRate": "0.187654",
            "orders": [
                {
                    "orderId": "order-a",
                    "goodsCharge": "690.69",
                    "feeCharge": "109.25",
                    "charge": "800",
                    "paidSum": "0",
                    "remaining": "800",
                    "profit": 111,
                },
                {
                    "orderId": "order-b",
                    "goodsCharge": "614.79",
                    "feeCharge": "109.25",
                    "charge": "724",
                    "paidSum": "100",
                    "remaining": "624",
                    "profit": 222,
                },
                {
                    "orderId": "order-self",
                    "goodsCharge": "115",
                    "feeCharge": "0",
                    "charge": "115",
                    "costShare": "99",
                    "paidSum": "0",
                    "remaining": "0",
                    "profit": 16,
                },
            ],
        },
        "members": [{"email": "hidden-buyer@example.com", "role": "editor"}],
        "payouts": [{"name": "卡片9981", "amount": "50"}],
        "role": "owner",
    }
    listed = {
        group_id: [
            flat("item-a1", group_id, "測試繪本", "2673", "/api/images/abc123def456"),
            flat("item-a2", group_id, "測試周邊", "330", "/api/images/fff123def456"),
            flat("item-b1", group_id, "測試繪本", "2673", "/api/images/abc123def456"),
            flat("item-s", group_id, "測試自留", "500", ""),
        ]
    }
    summary = [
        {"name": "買家甲", "charge": "800", "paidSum": "0", "remaining": "800"},
        {"name": "買家乙", "charge": "724", "paidSum": "100", "remaining": "624"},
        {"name": "團主", "charge": "0", "paidSum": "0", "remaining": "0", "isSelfOnly": True},
    ]
    public, images = project_publication(
        [detail],
        listed,
        summary,
        previous=None,
        billing_ids=[group_id],
        fetched_at="2026-11-08 08:00",
        empty_text="月中暫無款項請款",
    )
    encoded = json.dumps(public, ensure_ascii=False)
    assert public["gbs"][0]["rate"] == 0.23
    orders = {order["b"]: order for order in public["gbs"][0]["o"]}
    assert orders["買家甲"]["charge"] == 800
    assert orders["買家甲"]["gc"] == 691
    assert orders["買家甲"]["fc"] == 109
    assert orders["買家甲"]["rem"] == 800
    assert orders["買家乙"]["charge"] == 724
    assert orders["買家乙"]["paid"] == 100
    assert orders["買家乙"]["rem"] == 624
    assert orders["買家乙"]["pay"] == [[100, "2026-11-08", "測試轉帳", 0]]
    assert orders["團主"]["self"] == 1
    assert orders["團主"]["charge"] == 0
    assert orders["團主"]["sv"] == 115
    assert orders["團主"]["pay"] == []
    assert public["gbs"][0]["fees"] == [["測試運費", 950, "foreign"]]
    assert public["gbs"][0]["st"] == "closed"
    assert orders["買家甲"]["it"][0][3] == "ordered"
    assert images["abc123def456"] == "/api/images/abc123def456"
    for secret in ("costRate", "654321", "hidden-buyer@example.com", "卡片9981", "內部備註", "自行吸收回饋", "costShare"):
        assert secret not in encoded
    assert public["billing"]["items"][0]["amount"] == 800 + 624
    assert public["buyers"][0]["charge"] == 724 or public["buyers"][1]["charge"] == 724


def test_charge_stays_on_source_total_when_split_rounds_differently():
    group_id = "b" * 32
    detail = {
        "groupBuy": base_group(group_id),
        "orders": [
            {
                "id": "order-1",
                "buyerName": "買家丙",
                "isSelf": False,
                "items": [item("item-1", "差額品", "550", "")],
                "payments": [],
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": "order-1",
                    "goodsCharge": "126.4",
                    "feeCharge": "0",
                    "charge": "127",
                    "paidSum": "0",
                    "remaining": "127",
                }
            ]
        },
    }
    public, _images = project_publication(
        [detail],
        {group_id: [flat("item-1", group_id, "差額品", "550", "")]},
        [{"name": "買家丙", "charge": "127", "paidSum": "0", "remaining": "127"}],
        previous=None,
        billing_ids=[],
        fetched_at="2026-11-08 08:00",
        empty_text="沒有",
    )
    order = public["gbs"][0]["o"][0]
    assert order["gc"] == 126
    assert order["charge"] == 127
    assert order["rem"] == 127


def test_offset_flag_carries_forward_for_the_same_payment():
    group_id = "c" * 32
    previous = {
        "gbs": [
            {
                "id": group_id,
                "o": [
                    {
                        "b": "買家丁",
                        "pay": [[48, "2026-10-31", "測試抵扣", 1]],
                    }
                ],
            }
        ]
    }
    detail = {
        "groupBuy": base_group(group_id),
        "orders": [
            {
                "id": "order-1",
                "buyerName": "買家丁",
                "isSelf": False,
                "items": [item("item-1", "品項", "100", "")],
                "payments": [
                    {"amount": "48", "paidAt": "2026-10-31", "note": "測試抵扣"},
                    {"amount": "20", "paidAt": "2026-11-01", "note": "新的轉帳"},
                ],
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": "order-1",
                    "goodsCharge": "23",
                    "feeCharge": "0",
                    "charge": "23",
                    "paidSum": "68",
                    "remaining": "0",
                }
            ]
        },
    }
    public, _images = project_publication(
        [detail],
        {group_id: [flat("item-1", group_id, "品項", "100", "")]},
        [{"name": "買家丁", "charge": "23", "paidSum": "68", "remaining": "0"}],
        previous=previous,
        billing_ids=[],
        fetched_at="2026-11-08 08:00",
        empty_text="沒有",
    )
    flags = {payment[2]: payment[3] for payment in public["gbs"][0]["o"][0]["pay"]}
    assert flags == {"測試抵扣": 1, "新的轉帳": 0}


def test_item_status_mismatch_aborts():
    group_id = "d" * 32
    detail = {
        "groupBuy": base_group(group_id),
        "orders": [
            {
                "id": "order-1",
                "buyerName": "買家戊",
                "isSelf": False,
                "items": [item("item-1", "品項", "100", "")],
                "payments": [],
            }
        ],
        "fees": [],
        "settlement": {
            "orders": [
                {
                    "orderId": "order-1",
                    "goodsCharge": "23",
                    "feeCharge": "0",
                    "charge": "23",
                    "paidSum": "0",
                    "remaining": "23",
                }
            ]
        },
    }
    listed = [flat("item-1", group_id, "品項", "100", "")]
    listed[0]["status"] = "shipped"
    with pytest.raises(SchemaError, match="狀態"):
        project_publication(
            [detail],
            {group_id: listed},
            [{"name": "買家戊", "charge": "23", "paidSum": "0", "remaining": "23"}],
            previous=None,
            billing_ids=[],
            fetched_at="2026-11-08 08:00",
            empty_text="沒有",
        )


def item(item_id, name, price, image):
    return {
        "id": item_id,
        "name": name,
        "unitPrice": price,
        "quantity": 1,
        "status": "ordered",
        "shippingNumber": "",
        "image": image,
        "note": "品項內部備註",
        "store": "測試店",
        "orderNumber": "999",
    }


def flat(item_id, group_id, name, price, image):
    return {
        "id": item_id,
        "groupBuyId": group_id,
        "name": name,
        "unitPrice": price,
        "quantity": 1,
        "status": "ordered",
        "shippingNumber": "",
        "image": image,
    }


def base_group(group_id):
    return {
        "id": group_id,
        "name": "測試團",
        "source": "測試",
        "currency": "JPY",
        "status": "closed",
        "startedAt": "2026-11-07",
        "chargeRate": "0.23",
        "image": "",
        "url": "",
    }
