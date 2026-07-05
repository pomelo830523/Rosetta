"""DB 設定表查詢:白名單表、SELECT only、限制筆數(白名單來自 kb.config.yaml,per-app)。

回答「權重/規則的現值」——這類邏輯存在 DB,程式碼與 migration 檔都看不到現值。
連線參數直接解析該 app 的 application*.yml spring.datasource(不另存一份帳密)。
driver:mariadb(pymysql,已實測)/ oracle(python-oracledb,**尚未實測**,見 SPEC §4.7)。
"""

import re

from app_config import load_effective_config
from kb_config import AppContext

MAX_ROWS = 50

_MARIADB_URL_RE = re.compile(r"jdbc:(?:mariadb|mysql)://([^:/]+):(\d+)/([^?]+)")
_ORACLE_URL_RE = re.compile(r"jdbc:oracle:thin:@(?://)?([^:/]+):(\d+)[:/]([^?]+)")


def _connection_params(app: AppContext) -> dict:
    """從該 app 的 application*.yml spring.datasource 解析連線參數。"""
    config = load_effective_config(app)

    def raw(key: str) -> str:
        return config.get(key, ("", ""))[0]

    url = raw("spring.datasource.url")
    pattern = _ORACLE_URL_RE if app.db.driver == "oracle" else _MARIADB_URL_RE
    match = pattern.match(url)
    if not match:
        raise ValueError(
            f"無法以 {app.db.driver} 格式解析 spring.datasource.url:{url or '(未設定)'}"
        )
    host, port, database = match.groups()
    return {
        "host": host,
        "port": int(port),
        "database": database,
        "user": raw("spring.datasource.username"),
        "password": raw("spring.datasource.password"),
    }


def _fetch_mariadb(params: dict, table: str, limit: int) -> tuple[list[str], list[tuple]]:
    import pymysql
    connection = pymysql.connect(
        host=params["host"], port=params["port"], database=params["database"],
        user=params["user"], password=params["password"],
        charset="utf8mb4", connect_timeout=5, read_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            # table 名已通過白名單驗證,可安全內插;LIMIT 走參數繫結
            cursor.execute(f"SELECT * FROM {table} LIMIT %s", (limit,))
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
    finally:
        connection.close()
    return columns, list(rows)


def _fetch_oracle(params: dict, table: str, limit: int) -> tuple[list[str], list[tuple]]:
    # 尚未實測(無 Oracle 環境);首個 Oracle AP 導入時列為前置驗證項(SPEC §7)
    import oracledb
    connection = oracledb.connect(
        user=params["user"], password=params["password"],
        dsn=f"{params['host']}:{params['port']}/{params['database']}",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {table} FETCH FIRST :n ROWS ONLY", {"n": limit})
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
    finally:
        connection.close()
    return columns, list(rows)


def query_table(table: str, limit: int, app: AppContext) -> str:
    """查該 app 白名單設定表的現值,回傳 markdown 表格。"""
    name = table.strip().upper()
    sensitive_reason = app.db.sensitive_reason(name)
    if sensitive_reason:
        return f"「{name}」不可查詢:{sensitive_reason}"
    if name not in app.db.table_whitelist:
        allowed = ", ".join(app.db.table_whitelist) or "(此 app 未設定任何白名單表)"
        return (
            f"「{name}」不在 app「{app.name}」的查詢白名單。可查詢的設定表:{allowed}。"
            "本工具僅開放讀取設定表,一般業務資料表不開放。"
        )
    limit = max(1, min(int(limit), MAX_ROWS))

    try:
        params = _connection_params(app)
    except ValueError as exc:
        return f"連線參數解析失敗:{exc}"

    try:
        if app.db.driver == "oracle":
            columns, rows = _fetch_oracle(params, name, limit)
        else:
            columns, rows = _fetch_mariadb(params, name, limit)
    except ImportError as exc:
        return f"缺少 {app.db.driver} 的 DB driver 套件:{exc}(pip install 後重啟 server)"
    except Exception as exc:  # driver 各自的錯誤型別不同,統一轉為可讀訊息
        return (
            f"DB 連線或查詢失敗({params['host']}:{params['port']}/{params['database']},"
            f"table={name}):{exc}。請確認 DB 是否啟動(BestHouse 為 docker compose up -d)。"
        )

    if not rows:
        return f"{name} 目前沒有資料。"

    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| " + " | ".join("" if v is None else str(v) for v in row) + " |"
        for row in rows
    ]
    note = f"\n(來源:{app.name} DB 即時查詢,{name} 共回傳 {len(rows)} 筆,上限 {limit})"
    return "\n".join([header, divider, *body]) + note
