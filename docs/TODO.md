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
- [ ] 正式跑 `scripts/eval_e2e.py --set all`(清晰 10 + 模糊 5):
      模糊題釐清率、清晰題誤觸發 ≤ 1/10;超標則調 S2 門檻(Δ、模組數)。
      注意:請在**獨立終端機**跑(不要從 Claude Code session 內啟動——
      同帳號併發搶額度會被 rate-limit 拖到逾時;煙霧測試已驗證管線可通)

## Phase 10 — 維運與品質自動化 ✅(2026-07-06)

- [x] glossary lint(scripts/glossary_lint.py;index_all 附帶執行;
      besthouse 31 條 0 DEAD、1 warn 為概念性名詞 MariaDB,可接受)
- [x] log 報表(scripts/log_report.py:用量/耗時、S1~S3、S3 補詞候選、拒絕事件)
- [x] E2E 自動驗收腳本(scripts/eval_e2e.py:headless claude + 啟發式判分;
      煙霧測試通過管線,完整 15 題待正式跑——見 Phase 8 驗收項)
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

## Backlog — 變更歷史查詢(SPEC §4.10;git 量體評估中,暫不排程)

- [ ] 決策:輸出策略(只回 commit 訊息 vs -L 行範圍 vs 指定 commit 看 diff)
- [ ] 決策後:get_change_history tool + 截斷 + selftest

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
