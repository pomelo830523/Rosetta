"""kb.config.yaml 載入:multi-AP 設定(SPEC §4.7,一隊一台)。

一份 server code + 一份設定列 N 個 AP;所有 tools 以 `app` 參數選取 AppContext。
路徑解析規則:
  - repo_root:相對於 kb server 專案根(ROOT_DIR,rosetta/ 的上一層)解析
  - search_dirs / resources_dir / entity_dir:相對於 repo_root
  - glossary:相對於 config/ 目錄(對照表跟著 kb server 進版控,不放 AP repo)
設定檔以 mtime 快取失效:編輯 kb.config.yaml 後不需重啟 server
(但 MCP instructions 內的 AP 清單是啟動時組好的,新增/移除 AP 需重啟)。
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent  # kb server 專案根
CONFIG_DIR = ROOT_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "kb.config.yaml"
SEMANTIC_ROOT = ROOT_DIR / ".semantic"

VALID_ENGINES = ("auto", "semantic", "grep")
VALID_DRIVERS = ("mariadb", "oracle")


@dataclass(frozen=True)
class DbSettings:
    driver: str
    table_whitelist: tuple[str, ...]
    sensitive_tables: tuple[tuple[str, str], ...]  # ((TABLE, 排除理由), ...)

    def sensitive_reason(self, table: str) -> str:
        for name, reason in self.sensitive_tables:
            if name == table:
                return reason
        return ""


@dataclass(frozen=True)
class AppContext:
    name: str
    description: str
    repo_root: Path
    search_dirs: tuple[Path, ...]
    resources_dir: Path
    entity_dir: Path | None
    glossary_path: Path
    db: DbSettings
    engine: str          # auto | semantic | grep(global 可被 app 區塊覆蓋)
    embed_model: str     # 空字串 = semantic_common.DEFAULT_MODEL

    @property
    def index_dir(self) -> Path:
        """語意索引目錄(per-app):.semantic/<app>/"""
        return SEMANTIC_ROOT / self.name

    @property
    def codegraph_db(self) -> Path:
        return self.repo_root / ".codegraph" / "codegraph.db"


@dataclass(frozen=True)
class FleetApp:
    """艦隊目錄中「別的團隊管理的系統」(SPEC §4.10:本 server 只轉介,不查詢)。"""
    name: str
    description: str            # Claude 轉介路由的依據(list_apps 轉介區段)
    keywords: tuple[str, ...]   # 檢索空手時的字面比對轉介用


@dataclass(frozen=True)
class FleetEntry:
    server: str    # 對方 Rosetta 的 server 名稱;空字串 = 該團隊尚無 Rosetta
    team: str      # 負責團隊與聯絡窗口(必填:轉介至少要能告訴使用者找誰)
    endpoint: str  # 對方 MCP 連線端點或安裝說明(選填)
    docs: str      # 系統文件/wiki 連結(選填)
    apps: tuple[FleetApp, ...]


@dataclass(frozen=True)
class KbConfig:
    server_name: str
    apps: tuple[AppContext, ...]
    fleet: tuple[FleetEntry, ...] = ()

    def app_names(self) -> tuple[str, ...]:
        return tuple(a.name for a in self.apps)

    def resolve(self, name: str) -> tuple[AppContext | None, str]:
        """依 name 取 AppContext;name 為空且僅一個 AP 時回傳該 AP。

        回傳 (app, error_message):找不到時 app=None,error 給模型可讀的指引。
        """
        cleaned = (name or "").strip().lower()
        if not cleaned:
            if len(self.apps) == 1:
                return self.apps[0], ""
            return None, (
                "本 server 管理多個 AP,請帶 app 參數指定系統。"
                f"可用的 app:{', '.join(self.app_names())}(詳見 list_apps)。"
            )
        for app in self.apps:
            if app.name.lower() == cleaned:
                return app, ""
        return None, (
            f"沒有名為「{name}」的 app。可用的 app:{', '.join(self.app_names())}"
            "(不確定時先呼叫 list_apps 看各系統的描述)。"
        )


def _parse_db(raw: dict, app_name: str) -> DbSettings:
    driver = str(raw.get("driver") or "mariadb").lower()
    if driver not in VALID_DRIVERS:
        raise ValueError(f"app「{app_name}」的 db.driver 必須是 {VALID_DRIVERS},收到:{driver}")
    whitelist = tuple(str(t).upper() for t in (raw.get("table_whitelist") or []))
    sensitive = tuple(
        (str(k).upper(), str(v))
        for k, v in (raw.get("sensitive_tables") or {}).items()
    )
    return DbSettings(driver=driver, table_whitelist=whitelist, sensitive_tables=sensitive)


def _parse_app(raw: dict, defaults: dict) -> AppContext:
    if not isinstance(raw, dict):
        raise ValueError(
            f"kb.config.yaml 的 apps 清單有非 mapping 項目:{raw!r}(檢查 YAML 縮排)。")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("kb.config.yaml 有 app 區塊缺少 name。")
    if name.lower() == "all":
        raise ValueError("app name「all」為保留字(跨 AP 聯合查詢用,SPEC §4.9),請改名。")
    if not raw.get("repo_root"):
        raise ValueError(f"app「{name}」缺少 repo_root。")

    repo_root = (ROOT_DIR / str(raw["repo_root"])).resolve()
    engine = str(raw.get("engine") or defaults.get("engine") or "auto").lower()
    if engine not in VALID_ENGINES:
        raise ValueError(f"app「{name}」的 engine 必須是 {VALID_ENGINES},收到:{engine}")

    entity_dir_raw = raw.get("entity_dir")
    return AppContext(
        name=name,
        description=str(raw.get("description") or ""),
        repo_root=repo_root,
        search_dirs=tuple(repo_root / str(d) for d in (raw.get("search_dirs") or [])),
        resources_dir=repo_root / str(raw.get("resources_dir") or ""),
        entity_dir=(repo_root / str(entity_dir_raw)) if entity_dir_raw else None,
        glossary_path=(CONFIG_DIR / str(raw.get("glossary") or f"glossary/{name}.yaml")).resolve(),
        db=_parse_db(raw.get("db") or {}, name),
        engine=engine,
        embed_model=str(raw.get("embed_model") or defaults.get("embed_model") or ""),
    )


def _parse_fleet_app(raw: dict, team: str, local_names: set[str]) -> FleetApp:
    if not isinstance(raw, dict):
        raise ValueError(
            f"fleet 區塊「{team}」的 apps 有非 mapping 項目:{raw!r}(檢查 YAML 縮排)。")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError(f"fleet 區塊「{team}」有 app 缺少 name。")
    if name.lower() in local_names:
        raise ValueError(
            f"fleet app「{name}」與本 server 管理的 app 同名;"
            "fleet 只放其他團隊的系統,請改名或移除。")
    description = str(raw.get("description") or "").strip()
    if not description:
        raise ValueError(f"fleet app「{name}」缺少 description(Claude 轉介路由的依據)。")
    return FleetApp(
        name=name,
        description=description,
        keywords=tuple(str(k) for k in (raw.get("keywords") or [])),
    )


def _parse_fleet(data: dict, local_names: set[str]) -> tuple[FleetEntry, ...]:
    """fleet 轉介目錄(選填,SPEC §4.10):其他團隊的系統,只轉介不查詢。"""
    raw_list = data.get("fleet")
    if raw_list is None:
        return ()
    if not isinstance(raw_list, list):
        raise ValueError("kb.config.yaml 的 fleet 需要是清單。")
    entries = []
    for raw in raw_list:
        raw = raw or {}
        if not isinstance(raw, dict):
            raise ValueError(f"fleet 清單有非 mapping 項目:{raw!r}(檢查 YAML 縮排)。")
        team = str(raw.get("team") or "").strip()
        if not team:
            raise ValueError("fleet 有區塊缺少 team(轉介至少要能告訴使用者找誰)。")
        apps = tuple(_parse_fleet_app(a or {}, team, local_names)
                     for a in (raw.get("apps") or []))
        if not apps:
            raise ValueError(f"fleet 區塊「{team}」缺少 apps 清單。")
        entries.append(FleetEntry(
            server=str(raw.get("server") or "").strip(),
            team=team,
            endpoint=str(raw.get("endpoint") or "").strip(),
            docs=str(raw.get("docs") or "").strip(),
            apps=apps,
        ))
    fleet_names = [fa.name.lower() for e in entries for fa in e.apps]
    duplicated = {n for n in fleet_names if fleet_names.count(n) > 1}
    if duplicated:
        raise ValueError(
            f"fleet 有重複的 app name:{', '.join(sorted(duplicated))}"
            "(同一系統只登記一個負責團隊,轉介才不會混淆)。")
    return tuple(entries)


def _parse(text: str) -> KbConfig:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or not isinstance(data.get("apps"), list):
        raise ValueError("kb.config.yaml 格式錯誤:頂層需要 apps 清單。")
    defaults = {
        "engine": data.get("engine"),
        "embed_model": data.get("embed_model"),
    }
    apps = tuple(_parse_app(item or {}, defaults) for item in data["apps"])
    if not apps:
        raise ValueError("kb.config.yaml 的 apps 清單是空的,至少要設定一個 AP。")
    names = [a.name.lower() for a in apps]
    duplicated = {n for n in names if names.count(n) > 1}
    if duplicated:
        raise ValueError(f"kb.config.yaml 有重複的 app name:{', '.join(sorted(duplicated))}")
    return KbConfig(
        server_name=str(data.get("server_name") or "nl-query-kb"),
        apps=apps,
        fleet=_parse_fleet(data, set(names)),
    )


_cache: dict = {"stamp": None, "config": None}


def load_config() -> KbConfig:
    """讀取 kb.config.yaml(mtime 快取);檔案不存在或格式錯誤時 raise ValueError。

    刻意 fail fast:設定是管理員手寫的,錯了要立刻看到明確訊息,
    而不是讓 tools 各自回奇怪的結果。
    """
    if not CONFIG_PATH.is_file():
        raise ValueError(f"找不到設定檔:{CONFIG_PATH}。請依 QUICKSTART.md 建立 kb.config.yaml。")
    stamp = CONFIG_PATH.stat().st_mtime_ns
    if _cache["stamp"] != stamp:
        try:
            _cache["config"] = _parse(CONFIG_PATH.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"kb.config.yaml 不是合法 YAML:{exc}") from exc
        if _cache["stamp"] is not None:  # 首次載入由 kb_server 記,這裡只記「重新載入」
            import kb_log
            kb_log.setup().info(
                "kb.config.yaml 重新載入:%d 個 AP(%s)",
                len(_cache["config"].apps), ", ".join(_cache["config"].app_names()))
        _cache["stamp"] = stamp
    return _cache["config"]


def resolve_app(name: str = "") -> tuple[AppContext | None, str]:
    """kb_server 各 tool 的入口:回傳 (AppContext | None, 錯誤訊息)。"""
    try:
        return load_config().resolve(name)
    except ValueError as exc:
        return None, str(exc)
