# PLAN — NL Query KB

> 規格見 SPEC.md;待辦見 TODO.md。

## 已完成(至 2026-07-05)

- glossary(31 條 zh)、config tools(遮罩、白名單)、語意索引
  (e5-large、NL 訊號、content-hash 增量)、get_structure(codegraph schema v6)。
- multi-AP:kb.config.yaml + `app` 參數 + `list_apps`;隔離實測 13/13。
- 部署:streamable HTTP + `KB_AUTH_TOKEN`(401/通過實測)、`index_all.py`、
  `setup.ps1`、模板(`make_template.ps1` → `nl-query-kb-template/`)。
- MCP instructions(六條慣例)。selftest 26/26。
- MiniLM 驗證:索引快 15 倍、de 原文直查 miss → 預設維持 e5-large,MiniLM 為輕量選項。

## Phase 5 — 端到端驗收 ✅(2026-07-05,報告 eval/ACCEPTANCE.md)

- 題庫增至 10 題(code / DB / yml / 跨源);E2E 手動採分。
- zh **10/10**(來源正確、零幻覺、tools 選用正確、六條 instructions 無違反)≥ 9/10 門檻,通過。
- de/ja 各 2 題抽查:來源與 zh 一致、回答語言跟隨;唯 de q8(跨源)語意 top-3 偏「動作入口」,
  經 glossary/lookup_term 可回收 → 列根因 R1(檢索排序,非幻覺),建議依 instructions #4/#5 回收、暫不改檢索。
- 停損未觸發;glossary 與檢索層本輪不需回補。

## Phase 6 收尾(剩餘)

- Oracle driver 實測(程式就緒;等首個 Oracle AP 環境)。

## Phase 7 — 規模評估:一隊一台,百萬行以內 ✅(2026-07-05,報告 docs/ENTERPRISE-GAP.md)

- 定位:一隊一台,單台上限百萬行以內(≈5~10 萬 symbols);不追求單台千萬行。
- 結論:**此定位下現行架構基本不用改**——numpy 暴力內積(~40~100ms)、float32(400MB)、
  全檔重寫增量(400MB/秒級)在 10 萬 symbol 皆可接受。唯一摩擦是 e5-large CPU 首建(~9.7h,
  一次性),用 MiniLM(~35min)或借一次 GPU 即解。config/DB 查詢與行數脫鉤,glossary 線性小成本。
- 結構圖換 SCIP-Java 為邊的正確性(非規模);Oracle 為相容性——兩者定位內仍建議處理。
- 千萬行/跨團隊聚合(ANN、int8、GPU、分片)列為範圍外參考(ENTERPRISE-GAP.md §6)。

## Phase 8 — 歧義釐清(server 端實作完成 2026-07-05,SPEC §4.8;E2E 驗收待跑)

- 問題:使用者常問不清楚(「分數怎麼算」可指總分/維度分數/權重),
  現況 Claude 只能猜一個方向查,猜錯就答非所問。
- 作法(已實作):**server 加歧義訊號,反問由 Claude 執行**,分工原則(§1)不變:
  - S1 glossary 多義:`lookup_term` 命中多個**獨立**概念時附「請先確認是哪一個」提示
    (命中字串互不包含才算獨立,「不含車位單價」同時命中「車位」不誤觸發)。
  - S2 檢索分散:`search_code` 分數平坦(Δ<0.03)且命中散在 ≥3 個 class 時附「建議釐清」註記。
  - S3 檢索空手:無結果時附該 AP 的 glossary term 清單當選項素材(semantic/grep 皆同)。
  - S4 DB 多筆同名:instructions #7(b) 引導 Claude 從 query_db_config 回傳表格辨識
    多筆同名資料(實例:HOUSE 表 4 筆「竹科悅揚」),以識別欄位列選項確認;無需 server 偵測。
  - instructions 第 7 條:選項式(選項取自 KB 候選)、最多問一次、清楚就不問。
- 曾考慮並否決:新增 `clarify_question` tool(反問屬「懂」的一側,server 無從判斷
  使用者意圖,獨立 tool 只是多一次呼叫;tool 數維持 7)、glossary 加 `ask` 欄位
  (term/note 已足夠當選項,先不增加維護成本)。
- selftest 新增 6 項(S1×2/S2×3/S3×1)→ 33/33 通過;multi-AP 13/13 無回歸。
- 待辦:E2E 模糊題 5 題驗收;清晰 10 題誤觸發 ≤ 1/10(S2 的 Δ 門檻據此調校)。

## 風險

| 風險 | 緩解 |
|---|---|
| Claude 不遵守 instructions(不改寫查詢/不帶 app) | Phase 5 記錄遵守率;必要時 tool description 重申 |
| AP 路由錯誤 | description 寫使用者聽得懂的話;路由抽查 |
| 過度反問(問題清楚也被反問,使用者嫌煩) | instructions 限「最多問一次、清楚就不問」;S2 門檻以清晰題調校;eval 驗誤觸發 ≤ 1/10 |
| 呼叫圖缺 DI/反射邊(可用但不可信) | 回傳已標註;影響評估交叉確認;企業版換 SCIP/Spoon |
| 索引 staleness | 排程增量;config/DB/read_source 即時讀 |
| HTTP 認證依賴通道能力 | token 於反向代理注入,或維持內網信任 |
