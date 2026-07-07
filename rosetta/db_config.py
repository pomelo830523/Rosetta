"""DB 設定表查詢:白名單表、SELECT only、限制筆數(白名單來自 kb.config.yaml,per-app)。

回答「權重/規則的現值」——這類邏輯存在 DB,程式碼與 migration 檔都看不到現值。
連線參數直接解析該 app 的 application*.yml spring.datasource(不另存一份帳密)。
driver:mariadb(pymysql,已實測)/ oracle(python-oracledb,**尚未實測**,見 SPEC §4.7)。

受限過濾(SPEC §4.4):filter_column/filter_op/filter_value 組單一 WHERE 條件——
欄位名必須存在於該表實際 schema、運算子只有 eq/starts_with/contains、值一律參數繫結。
不是開放 WHERE:每個 SQL 組成都是封閉集合或繫結值。

DB 保護:starts_with(LIKE '值%')吃得到索引,contains('%值%')必然全表掃描;
另將執行時間上限下推到 DB 端(MariaDB max_statement_time / MySQL max_execution_time /
Oracle call_timeout),慢查詢由 DB 自己殺,不是只切斷 client。
"""

from dataclasses import dataclass
import re

from app_config import load_effective_config
from kb_config import AppContext
import kb_log

log = kb_log.setup()

MAX_ROWS = 50
VALID_FILTER_OPS = ("eq", "starts_with", "contains")
MAX_STATEMENT_SECONDS = 10  # DB 端執行時間上限(與 client read_timeout 對齊)


class FilterError(ValueError):
    """filter 條件不合法(欄位不存在等);訊息直接回給模型,供其自我修正。"""


@dataclass(frozen=True)
class TableFilter:
    column: str
    op: str      # eq | contains
    value: str

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


def _match_column(requested: str, columns: list[str]) -> str:
    """欄位名必須存在於該表實際 schema(不分大小寫);不存在時列出可用欄位。"""
    match = next((c for c in columns if c.upper() == requested.upper()), None)
    if match is None:
        raise FilterError(
            f"filter_column「{requested}」不存在於此表。可用欄位:{', '.join(columns)}")
    return match


def _escape_like(value: str) -> str:
    """contains 的值只當字面比對:跳脫 LIKE 萬用字元(escape 字元為反斜線)。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fetch_mariadb(params: dict, table: str, limit: int,
                   flt: TableFilter | None) -> tuple[list[str], list[tuple]]:
    import pymysql
    connection = pymysql.connect(
        host=params["host"], port=params["port"], database=params["database"],
        user=params["user"], password=params["password"],
        charset="utf8mb4", connect_timeout=5, read_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            # 執行時間上限下推:client read_timeout 只切斷連線,DB 端查詢仍會跑完;
            # 這裡讓 DB 自己殺超時查詢(MariaDB 用 max_statement_time 秒,
            # MySQL 用 max_execution_time 毫秒;各自不認得對方的變數名,擇一生效)
            for stmt in (f"SET SESSION max_statement_time={MAX_STATEMENT_SECONDS}",
                         f"SET SESSION max_execution_time={MAX_STATEMENT_SECONDS * 1000}"):
                try:
                    cursor.execute(stmt)
                except pymysql.err.Error:
                    continue
                break
            # table 名已通過白名單驗證,可安全內插;先取欄位清單驗證 filter_column
            cursor.execute(f"SELECT * FROM {table} LIMIT 0")
            columns = [desc[0] for desc in cursor.description]
            where, args = "", ()
            if flt:
                column = _match_column(flt.column, columns)
                if flt.op == "eq":
                    where, args = f" WHERE {column} = %s", (flt.value,)
                elif flt.op == "starts_with":
                    where, args = (f" WHERE {column} LIKE %s",
                                   (f"{_escape_like(flt.value)}%",))
                else:  # contains
                    where, args = (f" WHERE {column} LIKE %s",
                                   (f"%{_escape_like(flt.value)}%",))
            cursor.execute(f"SELECT * FROM {table}{where} LIMIT %s", (*args, limit))
            rows = cursor.fetchall()
    finally:
        connection.close()
    return columns, list(rows)


def _fetch_oracle(params: dict, table: str, limit: int,
                  flt: TableFilter | None) -> tuple[list[str], list[tuple]]:
    # 尚未實測(無 Oracle 環境);首個 Oracle AP 導入時列為前置驗證項(SPEC §7)
    import oracledb
    connection = oracledb.connect(
        user=params["user"], password=params["password"],
        dsn=f"{params['host']}:{params['port']}/{params['database']}",
    )
    # 執行時間上限(毫秒):超時由 driver 中斷該次呼叫,DB 端一併取消
    connection.call_timeout = MAX_STATEMENT_SECONDS * 1000
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table} FETCH FIRST 0 ROWS ONLY")
            columns = [desc[0] for desc in cursor.description]
            where = ""
            binds: dict = {"n": limit}
            if flt:
                column = _match_column(flt.column, columns)
                if flt.op == "eq":
                    where = f" WHERE {column} = :v"
                    binds["v"] = flt.value
                elif flt.op == "starts_with":
                    where = f" WHERE {column} LIKE :v ESCAPE '\\'"
                    binds["v"] = f"{_escape_like(flt.value)}%"
                else:  # contains
                    where = f" WHERE {column} LIKE :v ESCAPE '\\'"
                    binds["v"] = f"%{_escape_like(flt.value)}%"
            cursor.execute(
                f"SELECT * FROM {table}{where} FETCH FIRST :n ROWS ONLY", binds)
            rows = cursor.fetchall()
    finally:
        connection.close()
    return columns, list(rows)


def _parse_filter(filter_column: str, filter_op: str,
                  filter_value: str) -> TableFilter | None:
    """驗證 filter 參數組合;皆空回 None(整表行為)。不合法時 raise FilterError。"""
    column = (filter_column or "").strip()
    value = (filter_value or "").strip()
    if not column and not value:
        return None
    if not column:
        raise FilterError("有 filter_value 但缺 filter_column,請指定要過濾的欄位。")
    if not value:
        raise FilterError("有 filter_column 但缺 filter_value,請指定要比對的值。")
    op = (filter_op or "eq").strip().lower()
    if op not in VALID_FILTER_OPS:
        raise FilterError(f"filter_op 必須是 {' / '.join(VALID_FILTER_OPS)},收到:{filter_op}")
    return TableFilter(column=column, op=op, value=value)


def query_table(table: str, limit: int, app: AppContext,
                filter_column: str = "", filter_op: str = "eq",
                filter_value: str = "") -> str:
    """查該 app 白名單設定表的現值,回傳 markdown 表格;可選單一條件的受限過濾。"""
    name = table.strip().upper()
    sensitive_reason = app.db.sensitive_reason(name)
    if sensitive_reason:
        log.warning("query_db_config 敏感表被拒 app=%s table=%s", app.name, name)
        return f"「{name}」不可查詢:{sensitive_reason}"
    if name not in app.db.table_whitelist:
        log.warning("query_db_config 白名單外被拒 app=%s table=%s",
                    app.name, kb_log.brief(name))
        allowed = ", ".join(app.db.table_whitelist) or "(此 app 未設定任何白名單表)"
        return (
            f"「{name}」不在 app「{app.name}」的查詢白名單。可查詢的設定表:{allowed}。"
            "本工具僅開放讀取設定表,一般業務資料表不開放。"
        )
    limit = max(1, min(int(limit), MAX_ROWS))

    try:
        flt = _parse_filter(filter_column, filter_op, filter_value)
    except FilterError as exc:
        log.warning("query_db_config filter 參數不合法 app=%s table=%s:%s",
                    app.name, name, exc)
        return str(exc)

    try:
        params = _connection_params(app)
    except ValueError as exc:
        return f"連線參數解析失敗:{exc}"

    try:
        if app.db.driver == "oracle":
            columns, rows = _fetch_oracle(params, name, limit, flt)
        else:
            columns, rows = _fetch_mariadb(params, name, limit, flt)
    except ImportError as exc:
        return f"缺少 {app.db.driver} 的 DB driver 套件:{exc}(pip install 後重啟 server)"
    except FilterError as exc:  # 欄位不存在:回可用欄位清單供自我修正
        log.warning("query_db_config filter_column 驗證失敗 app=%s table=%s column=%s",
                    app.name, name, kb_log.brief(filter_column))
        return str(exc)
    except Exception as exc:  # driver 各自的錯誤型別不同,統一轉為可讀訊息
        log.error("DB 連線或查詢失敗 app=%s table=%s host=%s:%s:%s",
                  app.name, name, params["host"], params["port"], exc)
        return (
            f"DB 連線或查詢失敗({params['host']}:{params['port']}/{params['database']},"
            f"table={name}):{exc}。請確認 DB 是否啟動(BestHouse 為 docker compose up -d)。"
        )

    filter_desc = f"{flt.column} {flt.op}「{flt.value}」" if flt else ""
    if not rows:
        if flt:
            return f"{name} 沒有符合 {filter_desc} 的資料(欄位名正確,值無命中)。"
        return f"{name} 目前沒有資料。"

    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| " + " | ".join("" if v is None else str(v) for v in row) + " |"
        for row in rows
    ]
    note = (f"\n(來源:{app.name} DB 即時查詢,{name} 共回傳 {len(rows)} 筆,上限 {limit}"
            + (f",filter: {filter_desc}" if flt else "") + ")")
    if len(rows) >= limit:
        note += ("\n(警示:已達上限,結果可能不完整;"
                 "可用 filter_column/filter_value 縮小範圍。)")
    return "\n".join([header, divider, *body]) + note
