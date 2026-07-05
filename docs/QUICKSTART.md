# QUICKSTART — 團隊架設指南

> 對象:幫團隊架 NL Query KB 的工程師/管理員。使用者端說明:[USER-GUIDE.md](USER-GUIDE.md)。
> 架構規格:[SPEC.md](SPEC.md)。模板:`nl-query-kb-template/`(由 `make_template.ps1` 產生)。

## 原則

- **一隊一台**:不管幾個 AP 都只架一台 server;每個 AP 是設定檔裡的一個區塊
  (約 10 行)+ 一份對照表。「問題屬於哪個 AP」由 Claude 自動路由。
- **引擎依賴鏈**:codegraph 建圖 → 語意索引 → semantic(正式引擎)。
  `engine` 留 `auto`:索引未就緒時自動墊檔 grep(當天可用),就緒後自動切換。
- **集中部署**:server 架團隊內部伺服器(HTTP + token),使用者零安裝;
  repo 與 DB 帳密不落地使用者電腦。

每 AP 的成本:

| 準備項 | 成本 |
|---|---|
| 設定區塊(路徑、DB 白名單) | 10 分鐘 |
| DB 唯讀帳號(只給白名單表 SELECT) | 看 DBA |
| 對照表 `glossary/<app>.yaml` | 骨架起步,缺詞再補 |
| 索引 | `index_all.py` 批次,50 AP 排一晚 |

## 前置需求

- [ ] 內部伺服器(可 checkout 所有 AP repo)、Python 3.12+、Node.js(codegraph 用)
- [ ] 各 AP 的 DB 唯讀帳號
- [ ] (封閉環境)embedding model 離線 cache:可連網機器先建一次索引,整包帶入
- [ ] Claude 方案支援自訂 Connector(Team/Enterprise 可由管理員統一發佈)

## 架設步驟

### 1. 取得模板,跑 setup

```powershell
Copy-Item kb.config.yaml.example kb.config.yaml
powershell -ExecutionPolicy Bypass -File setup.ps1   # venv + 依賴 + .mcp.json + selftest
```

### 2. 填 kb.config.yaml(每 AP 一個區塊)

```yaml
apps:
  - name: besthouse
    description: 房屋喜好評估系統——房屋篩選、評分與權重   # Claude 路由依據
    repo_root: ..
    search_dirs: [besthouse-backend/src, besthouse-frontend/src]
    resources_dir: besthouse-backend/src/main/resources
    entity_dir: besthouse-backend/src/main/java/com/besthouse/entity
    glossary: glossary.yaml
    db:
      driver: mariadb
      table_whitelist: [RATING_DIMENSION, FILTER_RULE]
      sensitive_tables: {MEMBER: 含個資,排除}
engine: auto
```

- `description` 寫使用者聽得懂的一句話(路由準度取決於它)。
- `table_whitelist` 只放業務邏輯設定表;個資表一律不放(server 端強制)。
- 編輯即時生效,不需重啟。

### 3. 建索引

**3a. codegraph 建圖**(CLI 伺服器裝一次;圖每 AP 建一次):

```powershell
npm install -g @colbymchenry/codegraph
codegraph telemetry off

cd <AP 的 repo 根目錄>
codegraph init .        # 建呼叫圖與 symbol 目錄 → .codegraph/codegraph.db
codegraph status        # 確認索引完成
```

**3b. 語意索引**(掛排程,日常只需要這一支):

```powershell
.\.venv\Scripts\python.exe -X utf8 index_all.py --pull
# 逐 AP 自動執行:git pull → codegraph sync → 語意索引增量
# 沒建過圖的 AP 會列出提示(回到 3a),不擋其他 AP
```

`.venv/`、`.semantic/`、`.codegraph/` 進 `.gitignore`。

### 4. 填對照表(缺詞再補)

```powershell
.\.venv\Scripts\python.exe -X utf8 extract_glossary.py --app besthouse
```

從骨架挑高頻業務詞填 `glossary/<app>.yaml`(只需中文、只存名詞對應不存公式):

```yaml
- term: 房子分數
  aliases: [總分, 評分]
  it_terms: [HOUSE_RATING, HouseService.calculateScore]
  note: 各維度分數 × 權重加總,權重存於 DB
```

### 5. 啟動服務,發佈給使用者

```powershell
$env:KB_TRANSPORT = "http"
$env:KB_HTTP_HOST = "0.0.0.0"          # KB_HTTP_PORT 預設 8600
$env:KB_AUTH_TOKEN = "<team-token>"    # 不設 = 無認證,僅限信任內網
.\.venv\Scripts\python.exe -X utf8 kb_server.py
```

驗收(每個重點 AP 3+1 題):code 邏輯題附檔名:行號、DB 題回**現值**、
config 題密碼有遮罩、模糊問法路由到對的 AP。通過後把 Connector URL +
USER-GUIDE.md 發給使用者(Team/Enterprise 由管理員後台統一新增)。

### 6. 在 Claude Code 註冊 MCP

```powershell
claude mcp add --transport http rosetta http://localhost:8600/mcp --header "Authorization: Bearer <team-token>"
```

註冊後重啟 Claude Code,輸入 `/mcp` 看到 `rosetta` 且狀態 connected 即成功。

## 常見陷阱

1. **MCP `-32000`**:設定寫了裸 `python` 被解析到沒裝套件的 Python。
   一律用 venv 絕對路徑;真實錯誤看 `%LOCALAPPDATA%\claude-cli-nodejs\Cache\<project>\mcp-logs-*\`。
2. **cp950 編碼炸裂**:env 必設 `PYTHONUTF8=1`;`.ps1` 檔要 UTF-8 with BOM;
   會被 pip/python 以地區編碼讀的檔案(如 `requirements.txt`)只寫 ASCII,
   否則 zh-TW Windows 上 pip 直接 UnicodeDecodeError。
3. **搬目錄會壞**:venv 綁絕對路徑,搬移後重跑 `setup.ps1`。
4. **改了 server code** → 重啟服務(stdio 則 `/mcp` Reconnect);
   **AP code 有 commit** → 排程自動增量,手動則跑 `index_all.py`。
5. **路由不準** → 先改該 AP 的 `description`(太像系統代號就會不準)。
6. **呼叫圖缺邊**:tree-sitter 抓不到 DI/反射/interface 實作的邊,
   `get_structure` 說沒 caller 不等於沒人用;影響評估用全文搜尋交叉確認。

## 已知限制

- Oracle driver 未實測(程式就緒);首個 Oracle AP 導入前先驗。
- token 送法依 Claude 通道:不支援自訂 header 時在反向代理注入,或維持內網信任。
- embedding 預設 e5-large;AP 量大、索引時間敏感可改 MiniLM(`embed_model`,
  索引快 15 倍;經 Claude 歸一化後 zh/en 命中無差)。

## 時程參考(50 個 AP)

| 項目 | 時間 |
|---|---|
| 伺服器 + setup + 首個 AP 驗通 | 半天 |
| 50 個 AP 設定區塊 | 1~2 天(瓶頸在 DBA 給帳號) |
| 首建索引 | 一晚(之後增量分鐘級) |
| 對照表 | 缺詞再補,不排時程 |
