# PLAN — NL Query KB

> 規格見 SPEC.md;待辦見 TODO.md。

## 已完成(至 2026-07-05)

- glossary(31 條 zh)、config tools(遮罩、白名單)、語意索引
  (e5-large、NL 訊號、content-hash 增量)、get_structure(codegraph schema v5)。
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

## 風險

| 風險 | 緩解 |
|---|---|
| Claude 不遵守 instructions(不改寫查詢/不帶 app) | Phase 5 記錄遵守率;必要時 tool description 重申 |
| AP 路由錯誤 | description 寫使用者聽得懂的話;路由抽查 |
| 呼叫圖缺 DI/反射邊(可用但不可信) | 回傳已標註;影響評估交叉確認;企業版換 SCIP/Spoon |
| 索引 staleness | 排程增量;config/DB/read_source 即時讀 |
| HTTP 認證依賴通道能力 | token 於反向代理注入,或維持內網信任 |
