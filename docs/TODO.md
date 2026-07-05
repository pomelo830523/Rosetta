# TODO — NL Query KB

> 已完成項的摘要見 PLAN.md「已完成」。

## Phase 5 — 端到端驗收
- [ ] 補齊 10 題 zh 母本(涵蓋 code / DB / yml / 跨源;已有 5 題)
- [ ] 逐題實測(zh):來源正確性 / 幻覺 / tools 使用 / instructions 遵守率
- [ ] de / ja 各 2 題抽查(ja 存 eval/questions.ja.yaml):來源與 zh 版一致
- [ ] 驗收報告:通過率(門檻 zh ≥ 9/10)+ 失敗根因分類

## Phase 6 收尾
- [ ] Oracle driver 實測(db_config._fetch_oracle 就緒;等首個 Oracle AP 環境)

## Phase 7 — 企業化規模評估
- [ ] ENTERPRISE-GAP.md:引擎替換矩陣,每格標註信心等級(實測/試算/推測)
- [ ] 千萬行索引成本外推:首建時間 / 增量延遲 / 向量記憶體 / 分片
- [ ] glossary 成本攤平評估(每 AP 20~30 條 zh × N 個 AP)
- [ ] 回傳最佳化:回傳大小 vs token、附掛開關差異、instructions 遵守率
