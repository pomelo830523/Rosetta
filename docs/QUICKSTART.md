# QUICKSTART — 團隊架設指南

> 對象:幫團隊架 NL Query KB 的工程師/管理員。
> 架構規格:[SPEC.md](SPEC.md)。

## 原則

- **一隊一台**:每個團隊建置一台唯讀 MCP server，集中串接多個 AP;每個 AP 是設定檔裡的一個區塊
  (約 10 行)+ 一份對照表。「問題屬於哪個 AP」由 Claude 自動路由。
- **檢索引擎預設 grep**:命名尚可 + 有維護 glossary 時,語意索引相對 grep 幾乎零增益
  (SPEC §4.2、eval/ABLATION.md),且省掉 embedding 套件與每晚重建。大型 repo / 命名極差 /
  要 `app="all"` 跨 AP 探索的 AP,再把 `engine` 改 `semantic`(需裝 requirements-semantic.txt)。
- **集中部署**:server 架團隊內部伺服器(HTTP + token),使用者零安裝;
  repo 與 DB 帳密不落地使用者電腦。

每 AP 的成本:

| 準備項 | 成本 |
|---|---|
| 設定區塊(路徑、DB 白名單) | 10 分鐘 |
| DB 唯讀帳號(只給白名單表 SELECT) | 看 DBA |
| 對照表 `config/glossary/<app>.yaml` | 骨架起步,缺詞再補 |
| 索引 | `scripts/index_all.py` 批次,50 AP 排一晚 |

## 前置需求

- [ ] 內部伺服器(可 checkout 所有 AP repo)、Python 3.12+、Node.js(codegraph 用)
- [ ] 各 AP 的 DB 唯讀帳號
- [ ] (封閉環境)embedding model 離線 cache:可連網機器先建一次索引,整包帶入
- [ ] Claude 方案支援自訂 Connector(Team/Enterprise 可由管理員統一發佈)

## 架設步驟

### 0. 取得模板

server code 的**單一事實來源是 Rosetta 母站 repo**;模板 `nl-query-kb-template/`
由母站維護者執行 `scripts\make_template.ps1` 產生——含通用 server code
(`rosetta/`、`scripts/`)與空白設定範本,**不含**母站自己的 AP 設定、
對照表與題庫。取得方式二擇一:

- 向 Rosetta 維護團隊索取最新模板;或
- 自行 clone Rosetta repo 後執行:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\make_template.ps1
  # 輸出到 repo 旁的 nl-query-kb-template\(可用 -OutDir 指定位置)
  ```

把模板放上團隊的內部伺服器,**建議初始化成團隊自己的 git repo**——
之後填的 `config\kb.config.yaml` 與 `config\glossary\` 是團隊資產,要進版控;
`.venv/`、`.semantic/` 等產生物已在模板附的 `.gitignore` 排除。

### 1. 跑 setup

```powershell
Copy-Item config\kb.config.yaml.example config\kb.config.yaml
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1   # venv + 依賴 + .mcp.json 範本
```

`setup.ps1` 只裝核心依賴(`requirements.txt`,grep 引擎不需 embedding 套件)。
**只有要對某 AP 開 `engine: semantic`(或用 `app="all"` 探索)時**,才另外裝:
`.\.venv\Scripts\python.exe -m pip install -r requirements-semantic.txt`(fastembed + numpy)。

模板不含 selftest(那是母站針對它管的 AP 寫的),setup 最後一步顯示
「無 selftest,略過」屬正常;建議上線前仿母站的 `tests/selftest.py`
為你的 AP 寫一份,驗證項目照抄再改斷言即可。

### 2. 填 config/kb.config.yaml(每 AP 一個區塊)

路徑規則:`repo_root` 相對於 kb server 專案根(`config/` 的上一層);
`search_dirs` / `resources_dir` / `entity_dir` 相對於 repo_root;
`glossary` 相對於 `config/` 目錄。

```yaml
apps:
  - name: your-app               # app 參數值,短英文小寫;「all」為保留字不可用
    description: 一句話說明這個系統管什麼   # Claude 路由依據,寫使用者聽得懂的話
    repo_root: ../your-app       # 該 AP 在伺服器上的 checkout 路徑
    search_dirs: [backend/src, frontend/src]
    resources_dir: backend/src/main/resources
    entity_dir: backend/src/main/java/com/yourco/entity   # glossary 萃取用,可省略
    glossary: glossary/your-app.yaml
    db:
      driver: mariadb            # mariadb | oracle(oracle 程式就緒但未實測)
      table_whitelist: [YOUR_CONFIG_TABLE]
      sensitive_tables: {MEMBER: 含個資,排除}
engine: grep                     # 預設 grep;大型/命名極差/要 app=all 探索的 AP 再改 semantic
```

- `description` 寫使用者聽得懂的一句話(路由準度取決於它)。
- `table_whitelist` 只放業務邏輯設定表;個資表一律不放(server 端強制)。
- 編輯即時生效,不需重啟;**例外:新增/移除 AP 或 fleet 區段需重啟 server**
  (MCP instructions 的 AP 清單與轉介規則是啟動時組好的)。

**跨團隊轉介(選填)**:使用者常會問到「不歸這台管」的系統。可加 `fleet:`
目錄列出其他團隊的系統與窗口(寫法見 `config/kb.config.yaml.example` 的
fleet 區段,SPEC §4.10)——Claude 會引導使用者連對方的 Rosetta 續問,
或至少給負責團隊/文件連結;**對方團隊不需要先裝 Rosetta 就能列入**,
之後對方架了 Rosetta 補上 `endpoint` 即可。

> ⚠️ 反向提醒:當**你的** endpoint + token 被轉介給外團隊使用者時,
> 等同授予**你這台管理的所有 AP 的完整原始碼讀取權**(見「已知限制」),
> 發放前請確認可接受;揭露分級(guest token / 摘要層)已規劃未實作(TODO Phase 15)。

### 3. 建索引

**3a. codegraph 建圖**(CLI 伺服器裝一次;圖每 AP 建一次):

```powershell
npm install -g @colbymchenry/codegraph
codegraph telemetry off

cd <AP 的 repo 根目錄>
codegraph init .        # 建呼叫圖與 symbol 目錄 → .codegraph/codegraph.db
codegraph status        # 確認索引完成
```

**3b. 例行索引**(掛排程,日常只需要這一支):

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\index_all.py --pull
# 逐 AP 自動執行:git pull → codegraph sync →(engine≠grep 才)語意索引增量 → glossary lint
# 沒建過圖的 AP 會列出提示(回到 3a),不擋其他 AP
```

預設 `engine: grep` 的 AP 只做 codegraph sync(供 `get_structure`)與 glossary lint,
**不建語意索引**——不需要 3a 的圖也能用 grep 檢索與 config/DB 查詢(只是沒有
`get_structure`)。只有把某 AP 改成 `engine: semantic` 時才會建語意索引,且需先裝
`requirements-semantic.txt`(見步驟 1)。

gitignore 歸屬:`.venv/`、`.semantic/` 在 **kb server repo**(模板已附);
`.codegraph/` 在**各 AP repo**(請各 AP 團隊自行加入)。

### 4. 填對照表(缺詞再補)

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\extract_glossary.py --app your-app
```

從骨架挑高頻業務詞填 `config/glossary/<app>.yaml`(只需中文、只存名詞
對應不存公式)。未設定 `entity_dir` 的 AP 沒有骨架可萃取,直接手寫即可:

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
$env:KB_LOG_FILE  = "<路徑>\kb.log"    # 選填:log 落檔,供 log_report 彙整
.\.venv\Scripts\python.exe -X utf8 rosetta\kb_server.py
```

啟動後先驗活:`curl http://localhost:8600/health`——免認證,回各 AP 的
repo / codegraph / 語意索引狀態與 built_at。

驗收(每個重點 AP 3+1 題):code 邏輯題附檔名:行號、DB 題回**現值**、
config 題密碼有遮罩、模糊問法路由到對的 AP。通過後把 Connector URL
發給使用者(Team/Enterprise 由管理員後台統一新增)。

### 6. 在 Claude Code 註冊 MCP

```powershell
claude mcp add --transport http rosetta http://localhost:8600/mcp --header "Authorization: Bearer <team-token>"
```

註冊後重啟 Claude Code,輸入 `/mcp` 看到 `rosetta` 且狀態 connected 即成功。

## 日常維運

| 事項 | 做法 |
|---|---|
| 索引更新 | `scripts\index_all.py --pull` 掛排程(每晚);AP 有 commit 就會自動增量,已最新的 AP 幾乎零成本 |
| 對照表健康 | 排程輸出裡的 glossary lint:**DEAD 條目 = AP rename 後失效的對照,要修**;warn 多為概念性名詞可忽略 |
| 對照表補詞 | 定期跑 `scripts\log_report.py`(需 KB_LOG_FILE):報表中「S3 空手 query」就是使用者查了但 KB 接不住的詞,挑高頻的補進 glossary |
| 監控 | 排程打 `GET /health`;log 的 WARNING 是拒絕事件(白名單外查表/401 等),ERROR 是 DB 連線失敗 |
| 轉介目錄 | 其他團隊的系統有異動(換窗口/新架 Rosetta)時更新 `fleet:` 區段;條目內容修改即時生效,新增/移除區段需重啟 |
| server code 更新 | 母站發佈新模板後,以新模板的 `rosetta\` 與 `scripts\` **整目錄覆蓋**本地同名目錄,然後重啟 server。`config\`(你的設定與 glossary)模板不含、不會被蓋;requirements.txt 有變時重跑 setup |

## 進階:用實驗決定每個 AP 的引擎(grep vs 語意索引)

預設 `engine: grep`。要不要為某個 AP 額外建語意索引(改 `semantic` / `auto`),
**用數字決定,不要用猜的**——本專案附了一套逐 AP 量測實驗,完整協定見 `FLEET-EVAL.md`
(指標、干擾控制、統計嚴謹性)。到 50 AP / 百萬行規模時,決策重心是「延遲 + 建置成本」,
且必須逐 AP判定。判準(二選一「要不要建語意索引」):

1. grep 查詢 **p95 > 1s** → 建語意索引(大型 repo,延遲驅動,不看品質)。
2. grep 夠快、與 semantic top-k 高度重疊(Jaccard ≥ 0.6)、命名健康 → **grep**(等價又便宜)。
3. grep 夠快但分歧大 / 命名貧弱 → 標註 10~30 題,semantic 命中率贏 grep ≥ +10% 才值得建索引。

跑法(分階段,省建置成本):

```powershell
# Tier 1+2:全 AP 自動量測(規模/延遲/分歧/命名),不需標註 → eval\FLEET-REPORT.md
.\.venv\Scripts\python.exe -X utf8 scripts\fleet_eval.py --queries 60
#   報告把每個 AP 標成三類:延遲驅動要 semantic / grep 足矣 / 待 Tier 3

# 量 semantic 延遲與分歧前,該 AP 要先有語意索引(需先裝 requirements-semantic.txt):
.\.venv\Scripts\python.exe -X utf8 scripts\fleet_eval.py --app <app> --build-missing --queries 60

# Tier 3:對「待 Tier 3」的 AP 標註 eval\questions-<app>.yaml(格式見 FLEET-EVAL.md),再:
.\.venv\Scripts\python.exe -X utf8 scripts\eval_ablation.py --app <app> --langs zh,en
```

決策門檻(延遲預算、Jaccard、命中率 Δ、命名健康)都在 `scripts\fleet_eval.py` 頂部常數,
可依團隊需求調整;報告末段的「全艦隊匯總(rollup)」會加總「要建索引的 AP」之首建時間與常駐記憶體,
直接告訴你塞不塞得進維護窗與單機預算。

## 常見陷阱

1. **MCP `-32000`**:設定寫了裸 `python` 被解析到沒裝套件的 Python。
   一律用 venv 絕對路徑;真實錯誤看 `%LOCALAPPDATA%\claude-cli-nodejs\Cache\<project>\mcp-logs-*\`。
2. **cp950 編碼炸裂**:env 必設 `PYTHONUTF8=1`;`.ps1` 檔要 UTF-8 with BOM;
   會被 pip/python 以地區編碼讀的檔案(如 `requirements.txt`)只寫 ASCII,
   否則 zh-TW Windows 上 pip 直接 UnicodeDecodeError。
3. **搬目錄會壞**:venv 綁絕對路徑,搬移後重跑 `scripts/setup.ps1`。
4. **server code 更新後忘記重啟**(含模板同步覆蓋):tools 行為停在舊版;
   stdio 模式則 `/mcp` Reconnect。**AP code 有 commit** → 排程自動增量,
   手動則跑 `scripts/index_all.py`。
5. **路由不準** → 先改該 AP 的 `description`(太像系統代號就會不準)。
6. **呼叫圖缺邊**:tree-sitter 抓不到 DI/反射/interface 實作的邊,
   `get_structure` 說沒 caller 不等於沒人用;影響評估用全文搜尋交叉確認。

## 已知限制

- Oracle driver 未實測(程式就緒);首個 Oracle AP 導入前先驗。
- token 送法依 Claude 通道:不支援自訂 header 時在反向代理注入,或維持內網信任。
- **token = 完整原始碼讀取權**:拿到 token 的人可透過 `read_source` 分段讀出
  該台管理的**所有 AP 的整個 repo**(不限 search_dirs / 副檔名;敏感值遮罩僅
  涵蓋 yml/properties/.env)。對有 repo 權限的自己團隊無妨;**發 token 給
  外團隊(fleet 轉介情境)前請確認可接受**。揭露分級(guest token 不開
  read_source / server 端摘要層)已規劃未實作,見 TODO Phase 15 與 SPEC §7。
- embedding 預設 e5-large;AP 量大、索引時間敏感可改 MiniLM(`embed_model`,
  索引快 15 倍;經 Claude 改寫成 zh+en 檢索詞後命中無差)。

## 時程參考(50 個 AP)

| 項目 | 時間 |
|---|---|
| 伺服器 + setup + 首個 AP 驗通 | 半天 |
| 50 個 AP 設定區塊 | 1~2 天(瓶頸在 DBA 給帳號) |
| 首建索引 | 一晚(之後增量分鐘級) |
| 對照表 | 缺詞再補,不排時程 |
