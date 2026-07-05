# NL Query KB — 讓團隊用自然語言查系統邏輯

一台唯讀 MCP server 服務你團隊的 N 個 AP:使用者在 Claude 直接問
「這個功能的規則是什麼?」,答案來自當下真實的 code / config / DB,並附依據。

> 架設:QUICKSTART.md。

## 上手

```powershell
Copy-Item config\kb.config.yaml.example config\kb.config.yaml   # 填你的 AP 區塊(engine 留 auto)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

npm install -g @colbymchenry/codegraph            # CLI 裝一次
codegraph telemetry off
cd <AP repo 根>; codegraph init .                 # 每 AP 建一次圖

.venv\Scripts\python.exe -X utf8 scripts\index_all.py --pull   # 日常排程只掛這支
```

索引未建好之前 `auto` 自動以 grep 墊檔(當天可用),索引完成後自動切 semantic。

## 檔案

| 檔案 | 用途 |
|---|---|
| `rosetta/kb_server.py` | MCP server(7 個唯讀 tools;stdio / KB_TRANSPORT=http) |
| `rosetta/kb_config.py` | 讀 `config/kb.config.yaml`(multi-AP,編輯即時生效) |
| `rosetta/`(其餘) | 檢索引擎、glossary、config/DB/codegraph 存取模組 |
| `scripts/index_all.py` | 批次索引(--pull / --rebuild / --app;掛排程) |
| `rosetta/semantic_index.py` | 單 AP 語意索引(--app [--rebuild]) |
| `scripts/extract_glossary.py` | 對照表骨架萃取(--app) |
| `scripts/setup.ps1` | venv + 依賴 + .mcp.json + selftest |
| `config/glossary/` | 每 AP 一份對照表(只需中文;只存名詞對應不存公式) |

## 環境變數

| 變數 | 說明 |
|---|---|
| `KB_TRANSPORT` | `stdio`(預設)/ `http`(集中部署) |
| `KB_HTTP_HOST` / `KB_HTTP_PORT` | http 綁定,預設 127.0.0.1:8600 |
| `KB_AUTH_TOKEN` | http 的 Bearer 認證;未設定 = 僅限信任內網 |
| `KB_ENGINE` / `KB_EMBED_MODEL` | 臨時覆蓋引擎 / embedding model |

## 已知限制

- Oracle driver 就緒未實測;首個 Oracle AP 前先驗。
- 呼叫圖(tree-sitter)缺 DI/反射邊,影響評估請交叉確認。
- 封閉環境:embedding model 先在可連網機器建一次索引,把 fastembed cache 帶入。
- selftest 需按你的 AP 客製(參考 BestHouse 的 tests/selftest.py)。
- `.ps1` 檔要 UTF-8 with BOM;venv 綁絕對路徑,搬移後重跑 scripts\setup.ps1。
