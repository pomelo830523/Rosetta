# NL Query KB — 讓團隊用自然語言查系統邏輯

一台唯讀 MCP server 服務你團隊的 N 個 AP:使用者在 Claude 直接問
「這個功能的規則是什麼?」,答案來自當下真實的 code / config / DB,並附依據。

> 架設:QUICKSTART.md。

## 上手

```powershell
Copy-Item config\kb.config.yaml.example config\kb.config.yaml   # 填你的 AP 區塊(engine 預設 grep)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

npm install -g @colbymchenry/codegraph            # CLI 裝一次
codegraph telemetry off
cd <AP repo 根>; codegraph init .                 # 每 AP 建一次圖

.venv\Scripts\python.exe -X utf8 scripts\index_all.py --pull   # 日常排程只掛這支
```

預設 `engine: grep`:即時讀原始碼,不需 embedding、當天可用。語意索引為選配——
命名尚可 + 有維護 glossary 時相對 grep 幾乎零增益(見 QUICKSTART 與 SPEC §4.2);
大型 repo / 命名極差 / 要 `app="all"` 探索的 AP 才改 `engine: semantic`
(需 `pip install -r requirements-semantic.txt`)。

跨團隊轉介(選配):使用者常會問到「不歸你這台管」的系統。在 `kb.config.yaml`
加 `fleet:` 目錄(見 kb.config.yaml.example)列出其他團隊的系統與窗口,
Claude 就會引導使用者連對方的 Rosetta 續問,或至少給負責團隊/文件連結——
對方團隊不需要先裝 Rosetta 就能列進目錄。

## 檔案

| 檔案 | 用途 |
|---|---|
| `rosetta/kb_server.py` | MCP server(7 個唯讀 tools;stdio / KB_TRANSPORT=http) |
| `rosetta/kb_config.py` | 讀 `config/kb.config.yaml`(multi-AP,編輯即時生效) |
| `rosetta/`(其餘) | 檢索引擎、glossary、config/DB/codegraph 存取模組 |
| `scripts/index_all.py` | 批次索引(--pull / --rebuild / --app;掛排程) |
| `rosetta/semantic_index.py` | 單 AP 語意索引(--app [--rebuild]) |
| `scripts/extract_glossary.py` | 對照表骨架萃取(--app) |
| `scripts/setup.ps1` | venv + 依賴 + .mcp.json 範本(模板無 selftest,該步自動略過) |
| `config/glossary/` | 每 AP 一份對照表(只需中文;只存名詞對應不存公式) |

## 環境變數

| 變數 | 說明 |
|---|---|
| `KB_TRANSPORT` | `stdio`(預設)/ `http`(集中部署) |
| `KB_HTTP_HOST` / `KB_HTTP_PORT` | http 綁定,預設 127.0.0.1:8600 |
| `KB_AUTH_TOKEN` | http 的 Bearer 認證;未設定 = 僅限信任內網 |
| `KB_ENGINE` / `KB_EMBED_MODEL` | 臨時覆蓋引擎 / embedding model |
| `KB_LOG_LEVEL` / `KB_LOG_FILE` | log 等級(預設 INFO)/ log 檔路徑(log 一律走 stderr,設檔案則另寫一份) |

## 已知限制

- **token = 完整原始碼讀取權**:拿到 token 的人可透過 read_source 分段讀出
  本 server 管理的所有 AP 的整個 repo(遮罩僅涵蓋 yml/properties/.env)。
  發 token 給外團隊(fleet 轉介)前請確認可接受;揭露分級規劃中(QUICKSTART 已知限制)。
- Oracle driver 就緒未實測;首個 Oracle AP 前先驗。
- 呼叫圖(tree-sitter)缺 DI/反射邊,影響評估請交叉確認。
- 封閉環境(僅用到 `engine: semantic` 時):embedding model 先在可連網機器建一次索引,
  把 fastembed cache 帶入;純 grep 部署無此需求。
- selftest 需按你的 AP 客製(參考 BestHouse 的 tests/selftest.py)。
- `.ps1` 檔要 UTF-8 with BOM;venv 綁絕對路徑,搬移後重跑 scripts\setup.ps1。
