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

## Phase 5 — 端到端驗收(下一步)

1. 補齊 10 題 zh 母本(涵蓋 code / DB / yml / 跨源;已有 5 題)。
2. 逐題實測(zh):來源正確性、幻覺、tools 使用、instructions 遵守率。
3. de / ja 各 2 題抽查:來源與 zh 版一致、回答語言跟隨提問。
4. 驗收報告:通過率(zh ≥ 9/10)+ 失敗根因分類。

**停損**:zh < 9/10 → 回補 glossary 或檢索層,暫停後續。

## Phase 6 收尾(剩餘)

- Oracle driver 實測(程式就緒;等首個 Oracle AP 環境)。

## Phase 7 — 企業化規模評估

1. 工具合約搬到千萬行:哪些直接可用、哪些換引擎(每格標註 實測/試算/推測)。
2. 千萬行索引成本外推:首建時間、增量延遲、向量記憶體、分片。
3. glossary 成本:每 AP 20~30 條 zh × N 個 AP,萃取 pipeline 自動化程度。
4. 回傳最佳化:tool 回傳大小 vs token、呼叫鏈附掛開關差異、instructions 遵守率。

## 風險

| 風險 | 緩解 |
|---|---|
| Claude 不遵守 instructions(不改寫查詢/不帶 app) | Phase 5 記錄遵守率;必要時 tool description 重申 |
| AP 路由錯誤 | description 寫使用者聽得懂的話;路由抽查 |
| 呼叫圖缺 DI/反射邊(可用但不可信) | 回傳已標註;影響評估交叉確認;企業版換 SCIP/Spoon |
| 索引 staleness | 排程增量;config/DB/read_source 即時讀 |
| HTTP 認證依賴通道能力 | token 於反向代理注入,或維持內網信任 |
