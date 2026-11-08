"""同步會中止並保留上一筆公開資料的錯誤。"""


class SyncError(Exception):
    """同步沒有寫入公開資料。"""


class MissingToken(SyncError):
    """環境沒有 ORDERS_API_TOKEN。"""


class AuthError(SyncError):
    """來源拒絕授權或被擋下。不帶回應本文。"""


class SourceError(SyncError):
    """來源連線、狀態碼或位址不被接受。不帶回應本文。"""


class MissingImage(SourceError):
    """來源沒有這張圖片。"""


class SchemaError(SyncError):
    """投影結果或來源形狀不能安全公開。"""
