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

驗收與調校(待跑):
- [ ] eval 增模糊題 5 題(如「分數怎麼算」「為什麼被刷掉」「竹科悅揚單價」),
      E2E 驗:是否先釐清、選項是否來自 KB 候選、釐清後是否命中正確來源
- [ ] 既有清晰 10 題重跑:誤觸發反問 ≤ 1/10;超標則調 S2 門檻(Δ、模組數)
