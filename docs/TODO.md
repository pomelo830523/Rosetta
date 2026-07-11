# TODO — NL Query KB

> 已完成項的摘要見 PLAN.md「已完成」。

## Phase 5 — 端到端驗收 ✅(2026-07-05,報告見 eval/ACCEPTANCE.md)
- [x] 補齊 10 題 zh 母本(涵蓋 code / DB / yml / 跨源)
- [x] 逐題實測(zh):來源正確性 / 幻覺 / tools 使用 / instructions 遵守率 → 10/10
- [x] de / ja 各 2 題抽查:來源與 zh 版一致(de q8 檢索排序弱點,列 R1)
- [x] 驗收報告:zh 10/10 ≥ 9/10 通過 + 失敗根因分類(R1)

## Phase 6 收尾
- [ ] Oracle driver 實測(db_config._fetch_oracle 就緒;等首個 Oracle AP 環境)

## Phase 7 — 規模評估:一隊一台,百萬行以內 ✅(2026-07-05,報告 docs/ENTERPRISE-GAP.md)
- [x] 引擎是否夠用矩陣(百萬行內),每格標註信心等級(實測/試算/推測)
- [x] 百萬行索引成本外推(≈10 萬 symbols):首建時間 / 增量延遲 / 向量記憶體(不需分片)
- [x] glossary 成本攤平評估(每 AP 20~30 條 zh × N 個 AP)
- [x] 回傳最佳化:回傳大小 vs token、附掛開關差異、instructions 遵守率
- 註:千萬行/跨團隊聚合列為範圍外參考(ENTERPRISE-GAP.md §6)

## Phase 8 — 歧義釐清(SPEC §4.8;作法摘要見 PLAN.md)

實作(server 端訊號)✅ 2026-07-05:
- [x] S1 glossary 多義:`lookup_term` 命中 ≥ 2 個獨立概念時加提示行;
      命中字串互不包含才算獨立(車位⊂不含車位單價 不誤觸發)
      (rosetta/kb_server.py `_independent_concepts` + glossary.py `matched_candidates`)
- [x] S2 檢索分散:top1 − top3 < 0.03 且命中散在 ≥ 3 個 class 時,
      尾端附「結果分散,建議釐清」註記與模組清單(kb_server.py `_scatter_note`)
- [x] S3 檢索空手:semantic/grep 無結果時附該 AP glossary term 清單
      (kb_server.py `_glossary_domain_hint`)
- [x] S4 DB 多筆同名:instructions #7(b) + query_db_config docstring 引導
      (無需 server 偵測;實例:HOUSE 表 4 筆「竹科悅揚」)
- [x] instructions 第 7 條(改後需重啟 server;模板已重產)
- [x] selftest 加 6 項:S1 觸發/不誤觸發、S2 觸發/贏家/同 class、S3 清單 → 33/33

驗收與調校:
- [x] eval 模糊題 5 題(eval/questions-vague.yaml;S4/S1/不誤觸發等情境)
- [x] ~~正式跑 `scripts/eval_e2e.py --set all`~~ → **腳本已移除(2026-07-07)**:
      rate limit 退避使單題耗時不可控(60/240/600s 皆逾時),自動化不可靠;
      驗收改人工逐題實測(題庫保留:questions.yaml + questions-vague.yaml),
      誤觸發超標仍照原則調 S2 門檻(Δ、模組數)。決策記錄:SPEC §6。

## Phase 10 — 維運與品質自動化 ✅(2026-07-06)

- [x] glossary lint(scripts/glossary_lint.py;index_all 附帶執行;
      besthouse 31 條 0 DEAD、1 warn 為概念性名詞 MariaDB,可接受)
- [x] log 報表(scripts/log_report.py:用量/耗時、S1~S3、S3 補詞候選、拒絕事件)
- [x] E2E 自動驗收腳本(scripts/eval_e2e.py:headless claude + 啟發式判分;
      煙霧測試通過管線;**2026-07-07 移除**,原因見 Phase 8 驗收項與 SPEC §6)
- [x] HTTP GET /health(免認證監控;實測回 3 AP 索引狀態)
- [x] read_source start_line/end_line 範圍節錄
- [x] code_search 支援 *.html(行窗切塊)
- [x] selftest 新增 5 項 → 45/45;multi-AP 13/13 無回歸

## Phase 11 — 跨 AP 聯合查詢 ✅(2026-07-06,SPEC §4.9)

- [x] search_code / lookup_term 支援 app="all":逐 AP 分組、每 AP top 2、
      query 向量按 model 分組只嵌一次、只走 semantic(未建索引 AP 標註略過)
- [x] instructions #1 更新:all 僅供 discovery,找到歸屬必須切回單一 app;
      DB/config/read_source/get_structure 不開放 all
- [x] app name「all」列為 kb.config.yaml 保留字(載入時 fail fast)
- [x] selftest:all 分組輸出/命中/無內文/保留字 → 50/50;
      multi-AP:無索引 AP 略過、glossary 分組隔離 → 15/15
- [x] 實測跨 AP 路由:「產生條碼」→ zplviewer detectBarcodes(0.92~0.94)

## Phase 12 — 全專案 review 修正 ✅(2026-07-07)

- [x] HTTP 模式 tool 改 async offload(anyio.to_thread;同步 tool 會卡整個
      event loop,慢查詢期間所有使用者與 /health 全停;模組層維持同步供 tests)
- [x] get_app_config 動態掃 application*.yml/.yaml(原寫死兩檔名,
      application-prod.yml 等 profile 檔會靜默漏值;基底先、local 最後)
- [x] datasource URL port 改 optional(jdbc:mariadb://host/db 合法;預設 3306/1521)
- [x] Bearer 認證改全程 bytes 比對(非 ASCII header 原會 500 而非 401)
- [x] engine 鎖定 semantic 且索引未建時回可讀訊息(原丟 FileNotFoundError)
- [x] 語意索引 state 記 fastembed 版本(升版改 pooling 會讓檢索靜默劣化,
      版本變更視同 model 變更觸發全量重建)
- [x] 索引檔原子寫入(tmp + os.replace)+ 載入時驗證 meta/vectors 長度一致
- [x] graph_db sqlite 連線 contextlib.closing(with 只管 transaction 不管 close)
- [x] selftest 新增 5 項 → 57/57;multi-AP 15/15 無回歸

## Phase 13 — 全專案 review 修正第二輪 ✅(2026-07-08)

- [x] **read_source 遮罩繞道封堵**:讀 yml/yaml/properties/.env 時逐行套
      get_app_config 同款敏感值遮罩(app_config.mask_text;行數不變,
      行號引用不受影響)——原本直接讀 application*.yml 可拿到未遮罩密碼
- [x] search_code top_k 加上限 10(原無上限,top_k=999 會灌爆對話 context)
- [x] embedding model 載入加 threading.Lock(HTTP 併發首查會重複載入大模型)
- [x] glossary YAML 解析失敗改記 WARNING(原靜默回空表,boost/注入默默失效)
- [x] scripts 共用 --flag 參數解析(scripts/script_args.py;原四支腳本
      「--app 在結尾」會 IndexError traceback;log_report 順帶修掉
      --since 值被誤當 log 檔路徑的問題)
- [x] eval_retrieval 與 production 對齊:語料套 search_dirs 過濾
      (semantic_index.search_prefixes)、排序直接呼叫
      semantic_search.hybrid_rank(原是複製品,會漂移)
- [x] read_source end_line < start_line 回明確錯誤(原回空節錄)
- [x] semantic_index:search_dirs 未設定時明確略過(原默默建 0 symbol 索引)
- [x] KB_ENGINE 無效值啟動時警告,且不再覆蓋設定檔 engine(原靜默當 auto)
- [x] HTTP 層拆出 rosetta/http_transport.py(Bearer/health/uvicorn;
      kb_server 回到 MCP 層本體);list_apps 加註語意索引未建狀態
- [x] 刪除 code-kb-comparison.md(過時,模板本就排除)
- [x] selftest 新增 4 項 → 61/61;multi-AP 15/15 無回歸;模板重產

## Phase 14 — review 第三輪修正 + 單元測試 ✅(2026-07-08)

- [x] mask_text 補漏網形式:properties/.env「key=value」的敏感 key、
      yml block scalar(| / >)縮排續行、yml flow style 行內片段
      (TDD:先寫 4 個 RED 測試再實作)
- [x] glossary yaml 表頭註解欄位名修正:maps_to → it_terms
      (enhancesql / zplviewer;照舊註解寫的條目會被靜默忽略)
- [x] glossary_lint:it_terms 為空的條目給明確 DEAD 訊息(提示欄位名寫錯)
- [x] code_search.iter_source_files:search_dirs 巢狀/重疊時去重
- [x] db_config.TableFilter 註解補 starts_with
- [x] kb_log:KB_LOG_FILE 改 RotatingFileHandler(5MB × 3,不無限成長)
- [x] tests/selftest.py 移除重複 import;PLAN.md 補 Phase 12~14 摘要
- [x] **單元測試**:tests/unit/ 共 181 項(pytest + pytest-cov,
      requirements-dev.txt);不依賴 BestHouse repo / MariaDB / embedding model
      (tmp 假資產 + eval/fixture-app + monkeypatch embed / 假 pymysql /
      假 codegraph.db);coverage 81%(rosetta 各模組 79~100%,kb_server 84%)
- [x] selftest 61/61、multi-AP 15/15 無回歸;模板重產

## Phase 15 — 資訊揭露分級(規劃中,未實作;風險記錄 2026-07-10)

**風險**:token = 該台所有 AP 的完整原始碼讀取權(SPEC §7)。`read_source`
只限制在 repo_root 內,不限 search_dirs/副檔名,可分段讀出整個 repo;
遮罩僅涵蓋 yml/yaml/properties/.env。fleet 轉介(SPEC §4.10)把 endpoint +
token 發給外團隊時,等同授予完整原始碼讀取權——與「透過 Claude 問系統邏輯,
而不是拿到所有程式碼」的產品目標衝突。

規劃的改善路線(依序,前者是後者的前置):
- [ ] **token 分級**:`KB_AUTH_TOKEN`(團隊內,全功能)之外加 guest token
      (轉介用):不開 read_source,search_code 只回位置+簽名不含內文
- [ ] **限流/額度**:per-token 的 read_source 次數與每日回傳字元數上限 + 告警
      (回答邏輯問題只需幾次讀取,鏡像 repo 需要幾千次——讓外撈不可行且可見)
- [ ] **read_source 粒度與 denylist**:強制行號範圍(單次 ≤ ~200 行)、
      擋 `.git/`、`*.pem`、`id_rsa*` 等已知敏感模式、遮罩副檔名擴 `.json`
- [ ] **server 端摘要層 `explain_logic(question, app)`**(終局形態,使用者
      真正想做的):server 自帶 LLM 跑檢索工作流(重用現有函式當 tool、
      instructions 當 system prompt),只回「邏輯說明 + 檔名:行號依據」,
      原始碼不跨信任邊界;輸出濾網強制引用 ≤ N 行。估 3~5 天。
      **前置未定:公司內 LLM 來源(API key / 內部 gateway / 網路政策)**,
      確定後再開工。

## 決定不做(記錄於 SPEC §6 非目標)
- 變更歷史查詢(get_change_history):git 歷史量體風險 > 價值,2026-07-06 定案不做

## Phase 9 — query_db_config 受限過濾 ✅(2026-07-05,SPEC §4.4)

實作(rosetta/db_config.py + kb_server.py):
- [x] 新增選填參數 filter_column / filter_op(eq|contains)/ filter_value;
      三者皆空 = 原整表行為(向下相容)
- [x] 欄位名驗證:連線後以 driver metadata 取該表實際欄位(不分大小寫比對);
      不存在時拒絕並回可用欄位清單(供 Claude 自我修正)
- [x] 值一律參數繫結;contains 包 %value% 並跳脫 % _ \(LIKE 僅字面比對)
- [x] Oracle 分支同步(FETCH FIRST + :v 繫結 + ESCAPE;維持「未實測」標註)
- [x] 截斷警示:回傳筆數 = limit 時尾註加警示(無過濾時也適用)
- [x] tool docstring 更新:查特定對象時建議用 filter,與 S4 配合

驗證:
- [x] selftest 新增 7 項:欄位不存在/注入字串被拒/eq 命中 4 筆同名(不分大小寫)/
      contains/未知 op/萬用字元跳脫/截斷警示 → 40/40;multi-AP 13/13 無回歸
- [x] README 工具表、模板重產、server 重啟(tool 簽名變更)
