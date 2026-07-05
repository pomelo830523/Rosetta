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
