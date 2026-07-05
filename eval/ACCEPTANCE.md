# Phase 5 端到端驗收報告

> 驗收日期:2026-07-05。對象 AP:besthouse。題庫:`eval/questions.yaml`(10 題,zh/en/de/ja 內嵌單檔)。
> 採分方式:**E2E 手動採分**——實際呼叫 rosetta MCP tools 回答每題,人工核對四項:
> **來源正確性 / 幻覺 / tools 使用 / 六條 instructions 遵守**。
> (retrieval 命中率的模型對比另見 `eval/RESULT.md`,非本報告範圍。)

## 一、通過率與門檻

| 項目 | 結果 | 門檻 | 判定 |
|---|---|---|---|
| zh 母本 | **10 / 10** | ≥ 9 / 10 | ✅ 通過 |
| de 抽查 | 1.5 / 2(q1 完全一致、q8 部分) | 參考 | ⚠ 見根因 R1 |
| ja 抽查 | 2 / 2 | 參考 | ✅ |

**結論:zh 10/10 ≥ 9/10,Phase 5 通過。** 停損條件(zh < 9/10)未觸發。
de q8 暴露一個跨源檢索排序弱點,列為改善項(非阻斷)。

## 二、zh 逐題結果

| id | 類型 | 使用 tools | 權威來源(核對) | 來源正確 | 幻覺 | instructions 遵守 |
|---|---|---|---|:-:|:-:|---|
| q1 | code | search_code | FilterService.calcPricePerPingWithoutParking:302 / HouseService.calculatePricePerPingWithoutParking:321(已知重複兩份) | ✅ | 無 | #3 業務詞→IT 詞展開 ✅;附檔名:行號 ✅ |
| q2 | code→cross | lookup_term→get_structure | ScoreService.calculateRanking:35-87;權重來自 RatingDimensionRepository(DB) | ✅ | 無 | #4 呼叫鏈追 callees ✅;#5 權重指向 DB 未硬編 ✅ |
| q3 | code | search_code | HouseService.calculateMonthlyMortgage:287(總價×0.8、年利率 2.6%、360 期) | ✅ | 無 | 公式以程式碼為準 ✅ |
| q4 | code | search_code | House.eliminatedReason:159 / HouseDto.eliminatedReason:74 | ✅ | 無 | ✅ |
| q5 | code | search_code | HouseService.calculateInterestToRentRatio:313 | ✅ | 無 | ✅ |
| q6 | db | query_db_config(RATING_DIMENSION) | 8 維度 WEIGHT 現值(地點與交通 0.40、生活機能/價格性價比各 0.15…) | ✅ | 無 | #5 查 DB 現值、不引程式碼舊值 ✅ |
| q7 | yml | get_app_config(datasource) | spring.datasource.url = jdbc:mariadb://localhost:3306/besthouse;password 已遮罩 | ✅ | 無 | 敏感值遮罩 ✅ |
| q8 | cross | search_code(FilterRuleType)+ query_db_config(FILTER_RULE) | 16 種 FilterRuleType(code)+ 11 條啟用門檻現值(DB:MAX_TOTAL_PRICE 3100、MAX_HOUSE_AGE 12…) | ✅ | 無 | #4/#5 跨源合流 ✅ |
| q9 | yml | lookup_term/search_code + get_app_config(gemini) | AiImportService.extractFromImage(Gemini);gemini.api-key 已遮罩 | ✅ | 無 | 敏感 key 遮罩 ✅ |
| q10 | db | query_db_config(MEMBER) | 明確拒絕:「含家庭成員個人權重(個資),已排除於查詢白名單」 | ✅ | 無(未編造) | 敏感表拒絕並給理由、不裝作不存在 ✅ |

四項全數通過:來源正確 10/10、零幻覺、tools 選用皆正確、六條 instructions 無違反。

## 三、de / ja 抽查

| lang | id | 類型 | 結果 | 說明 |
|---|---|---|---|---|
| de | q1 | code | ✅ 一致 | top-3 含 FilterService/HouseService 兩份實作,與 zh 版同源 |
| de | q8 | cross | ⚠ 部分 | 語意 top-3 排出 applyFilters 入口流程(前端+controller),未把 FilterRuleType enum / FILTER_RULE 表排進 top-3;經 glossary it_terms(lookup_term)仍可回收正確來源 |
| ja | q1 | code | ✅ 一致 | 與 zh 同源 |
| ja | q2 | code | ✅ 一致(更佳) | top-3 直接命中 ScoreService.calculateRanking 完整公式,優於 zh 需 get_structure 補追 |

回答語言皆跟隨提問語言;來源與 zh 母本一致(q8 除外,見 R1)。

## 四、失敗根因分類

- **R1 — 跨源問題的語意排序偏向「動作入口」而非「規則定義」(de q8)**
  - 現象:德文「有哪些篩選規則、門檻多少」語意最近鄰是 `applyFilters`(套用動作),
    而非 `FilterRuleType`(種類定義)與 `FILTER_RULE`(門檻現值)。
  - 影響:純語意 top-3 需再一跳(lookup_term/query_db_config)才補齊;答案仍正確,只是多一步。
  - 分類:**檢索排序**(非幻覺、非來源錯誤)。
  - 緩解(擇一,待定案):
    (a) glossary「篩選規則」note 補一句「種類看 FilterRuleType、門檻現值查 FILTER_RULE 表」加強反向注入;
    (b) 依賴既有 instructions #4/#5(工具已能回收),不改檢索;
    (c) 對 enum 類 symbol 的 NL 訊號加權(semantic_index)。
  - 建議:先採 (b)(零成本、已驗證可回收),若後續多 AP 重演再評估 (a)。

## 五、備註

- 未觸發停損;glossary 與檢索層本輪不需回補。
- q1 觀察到 `calcPricePerPingWithoutParking`(FilterService)與 `calculatePricePerPingWithoutParking`(HouseService)
  兩份重複實作、且車位價估算的 null 防呆略有差異——屬受測 AP(besthouse)自身的既有技術債,非本 KB 缺陷,僅記錄。
