# Rosetta — 系統邏輯查詢 MCP(multi-AP)

一台唯讀 MCP server 服務 N 個 AP:使用者用任何語言問系統邏輯,
Claude 讀當下真實的 code / config / DB 後回答並附依據。
目前管理的 AP:besthouse、enhancesql、zplviewer(見 `config/kb.config.yaml`)。

> 規格:`docs/SPEC.md`;架設:`docs/QUICKSTART.md`。

## 工具(7 個,全部唯讀)

| 工具 | 說明 |
|------|------|
| `list_apps()` | 列出管理的 AP 與描述(Claude 路由用) |
| `lookup_term(query, app)` | 業務用語 → IT 對照(class/method/DB 欄位/config key) |
| `search_code(query, top_k, app, include_call_chain)` | 語意檢索原始碼,回 symbol 原文 |
| `get_structure(symbol, app)` | callers / callees / 定義位置(codegraph 圖) |
| `read_source(relative_path, app)` | 讀完整檔案(限該 AP 專案根內) |
| `get_app_config(key_pattern, app)` | 查 `application*.yml`;敏感值遮罩 |
| `query_db_config(table, limit, app, filter_column, filter_op, filter_value)` | 查 DB 設定表現值;白名單 + SELECT only;受限過濾(eq/contains,欄位名驗證、值繫結) |

`app` 參數:單一 AP 時可省略。唯讀保證:不寫檔、不執行、DB 只 SELECT 白名單表、
codegraph.db 以 read-only 開啟。

## 專案結構

```
rosetta/               server 核心(MCP 層與檢索引擎)
  kb_server.py         MCP 層(7 tools、instructions、防目錄穿越、app 路由、HTTP+token)
  kb_config.py         config/kb.config.yaml → AppContext(per-AP 路徑/DB/glossary)
  glossary.py          對照表比對/展開/boost
  semantic_search.py   語意檢索(向量內積 + 字面 boost;不掃 repo)
  semantic_index.py    語意索引建置(NL 訊號 embedding;content-hash 增量)
  graph_db.py          codegraph.db 唯讀存取(schema v6 鎖定)
  code_search.py       grep 引擎(auto 的自動墊檔:索引未就緒/損壞時)
  app_config.py        application*.yml 解析(local 覆蓋 base、敏感遮罩)
  db_config.py         DB 設定表查詢(mariadb 實測;oracle 就緒未實測)
scripts/               維運腳本
  index_all.py         批次索引(--pull / --rebuild / --app)
  extract_glossary.py  對照表骨架萃取(--app)
  eval_retrieval.py    embedding 模型評測(eval/ 題庫)
  setup.ps1            venv + 依賴 + .mcp.json 範本 + selftest
  make_template.ps1    產出通用模板(nl-query-kb-template/;code 只在這裡維護)
tests/                 selftest.py(功能驗證)、selftest_multiapp.py(multi-AP 隔離)
config/                kb.config.yaml + glossary/<app>.yaml(團隊資產,進版控)
eval/                  題庫、驗收基準、fixture app
docs/                  SPEC / QUICKSTART / PLAN / TODO / ENTERPRISE-GAP
```

## 常用操作

```powershell
# 安裝 / 搬移後重建
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 索引更新(AP code 有 commit 後跑這個:自動 git pull → codegraph sync → 語意增量)
.\.venv\Scripts\python.exe -X utf8 scripts\index_all.py --pull

# 集中部署(HTTP;stdio 開發模式由 .mcp.json 自動叫起)
$env:KB_TRANSPORT="http"; $env:KB_AUTH_TOKEN="<token>"
.\.venv\Scripts\python.exe -X utf8 rosetta\kb_server.py

# 驗證
.\.venv\Scripts\python.exe -X utf8 tests\selftest.py           # 功能驗證
.\.venv\Scripts\python.exe -X utf8 tests\selftest_multiapp.py  # multi-AP 隔離
```

改了 server code → 重啟(stdio 則 `/mcp` Reconnect),並重跑 `scripts\make_template.ps1`
同步模板。索引重建後 server 不用重啟;**新增/移除 AP 需重啟**(MCP instructions 的
AP 清單是啟動時組好的)。環境變數:`KB_TRANSPORT`、`KB_HTTP_HOST/PORT`、
`KB_AUTH_TOKEN`、`KB_ENGINE`、`KB_EMBED_MODEL`。

## 注意

- 權重/門檻的**現值只在 DB**,程式碼與 migration 看不到。
- glossary 只維護 zh、只存名詞對應不存公式;編輯後需重跑索引(觸發該 AP 全量)。
- codegraph 圖缺 DI/反射邊;中文 docstring 亂碼已繞過(註解由 kb 自抽 UTF-8)。
- venv 綁絕對路徑;`.ps1` 要 UTF-8 with BOM。
