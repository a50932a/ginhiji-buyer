"""向 money.klab.tw 讀取訂單。只送出 GET，權杖只加在這個主機。"""

from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from sync.errors import AuthError, MissingImage, SchemaError, SourceError

USER_AGENT = "money-orders-agent/1.0"
MAX_JSON_BYTES = 20_000_000
MAX_IMAGE_BYTES = 8_000_000
Resolver = Callable[..., list]


class OrdersClient:
    def __init__(
        self,
        token: str,
        *,
        base: str = "https://money.klab.tw",
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        cleaned = token.strip()
        if not cleaned or any(char in cleaned for char in "\r\n"):
            raise AuthError("缺少授權")
        self.base = base.rstrip("/")
        self._token = cleaned
        self._resolver = resolver or socket.getaddrinfo
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(30.0),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )

    def __repr__(self) -> str:
        return f"OrdersClient(base={self.base})"

    def close(self) -> None:
        self._client.close()

    def list_groups(self) -> list[dict]:
        path = "/api/orders/group-buys"
        found: dict[str, dict] = {}
        for _ in range(20):
            payload = self._get_json(path)
            rows, nxt = _group_rows(payload)
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    raise SchemaError("團購清單格式無法辨識")
                found.setdefault(str(row["id"]), row)
            if not nxt:
                return list(found.values())
            path = self._same_api(nxt)
        raise SchemaError("團購清單分頁超過上限")

    def get_group(self, group_id: str) -> dict:
        payload = self._get_json(f"/api/orders/group-buys/{group_id}")
        if not isinstance(payload, dict) or "groupBuy" not in payload or "orders" not in payload or "settlement" not in payload:
            raise SchemaError("團購明細格式無法辨識")
        if str(payload.get("groupBuy", {}).get("id")) != group_id:
            raise SchemaError("團購明細 id 不符")
        return payload

    def get_items(self, group_id: str) -> list[dict]:
        payload = self._get_json(f"/api/orders/items?groupBuyId={group_id}")
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise SchemaError("品項清單格式無法辨識")
        return payload["items"]

    def buyers_summary(self, group_ids: list[str]) -> list[dict]:
        joined = ",".join(group_ids)
        payload = self._get_json(f"/api/orders/buyers/summary?ids={joined}")
        if not isinstance(payload, dict) or not isinstance(payload.get("buyers"), list):
            raise SchemaError("買家總覽格式無法辨識")
        return payload["buyers"]

    def stat_image(self, url: str) -> str | None:
        response = self._request("HEAD", self._absolute(url), "image/*", MAX_IMAGE_BYTES)
        if response.status_code == 405:
            return None
        if response.status_code == 404:
            raise MissingImage("圖片不存在")
        if response.status_code != 200:
            raise SourceError("圖片狀態不正確")
        return response.headers.get("etag")

    def get_image(self, url: str) -> tuple[bytes, str | None]:
        response = self._request("GET", self._absolute(url), "image/*", MAX_IMAGE_BYTES)
        if response.status_code == 404:
            raise MissingImage("圖片不存在")
        if response.status_code != 200:
            raise SourceError("圖片下載失敗")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            raise SourceError("回應不是圖片")
        return response.content, response.headers.get("etag")

    def _get_json(self, path: str):
        response = self._request("GET", self.base + path, "application/json", MAX_JSON_BYTES)
        if response.status_code != 200:
            raise SourceError("來源狀態不正確")
        try:
            return json.loads(response.content.decode("utf-8"), parse_float=str)
        except (UnicodeError, json.JSONDecodeError):
            raise SchemaError("來源不是 JSON") from None

    def _absolute(self, url: str) -> str:
        if url.startswith("https://"):
            return url
        if url.startswith("/"):
            return self.base + url
        raise SourceError("網址不正確")

    def _same_api(self, url: str) -> str:
        parts = urlsplit(urljoin(self.base + "/", url))
        if parts.scheme != "https" or parts.hostname != urlsplit(self.base).hostname:
            raise SourceError("分頁網址超出訂單 API")
        if not parts.path.startswith("/api/orders/"):
            raise SourceError("分頁網址超出訂單 API")
        query = f"?{parts.query}" if parts.query else ""
        return parts.path + query

    def _request(self, method: str, url: str, accept: str, limit: int) -> httpx.Response:
        current = url
        current_method = method
        for _ in range(5):
            self._reject_unroutable(current)
            headers = {"Accept": accept, "User-Agent": USER_AGENT}
            headers.update(self._authorization(current))
            try:
                response = self._client.request(current_method, current, headers=headers)
            except httpx.HTTPError:
                raise SourceError("連線失敗") from None
            if len(response.content) > limit:
                raise SourceError("回應過大")
            if response.status_code in (401, 403):
                raise AuthError("來源拒絕授權")
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise SourceError("重新導向沒有位置")
                current = urljoin(current, location)
                if response.status_code in (301, 302, 303):
                    current_method = "GET"
                continue
            if response.status_code >= 500 or response.status_code == 429:
                raise SourceError("來源暫時失敗")
            return response
        raise SourceError("重新導向次數過多")

    def _authorization(self, url: str) -> dict[str, str]:
        host = urlsplit(url).hostname
        if host == urlsplit(self.base).hostname:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def _reject_unroutable(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise SourceError("只接受 https")
        if parts.username or parts.password:
            raise SourceError("網址含有認證資訊")
        host = parts.hostname.rstrip(".").lower()
        if host in {"localhost", "metadata.google.internal"}:
            raise SourceError("拒絕內網位址")
        try:
            infos = self._resolver(host, None)
        except socket.gaierror:
            raise SourceError("無法解析主機") from None
        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if not address.is_global:
                raise SourceError("拒絕非公開位址")


def _group_rows(payload) -> tuple[list, str | None]:
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict) and isinstance(payload.get("groupBuys"), list):
        nxt = payload.get("next")
        if nxt is not None and not isinstance(nxt, str):
            raise SchemaError("團購清單分頁格式無法辨識")
        return payload["groupBuys"], nxt or None
    raise SchemaError("團購清單格式無法辨識")
