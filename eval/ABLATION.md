# 語意索引 vs grep 消融實驗結果

- 對象:besthouse(10 題)| top-k=3 | 同 glossary、同 expected 判定
- semantic:預建 e5-large 索引;grep:即時讀原始碼 | 耗時 8s
- 命中 = top-k 任一回傳區塊(檔案路徑+程式原文)含 expected 子字串

## 各語言命中率
| 引擎 | zh | en | de | ja | 全語言 | zh+en(production 實境) |
|---|---|---|---|---|---|---|
| semantic | 9/10 | 9/10 | 7/10 | 8/10 | 33/40 | 18/20 |
| grep | 9/10 | 8/10 | 8/10 | 6/10 | 31/40 | 17/20 |

## 逐題對照(zh / en)
| id | type | expected | semantic zh/en | grep zh/en |
|---|---|---|---|---|
| q1 | code | `priceperpingwithoutparking` | ✅ / ✅ | ✅ / ✅ |
| q2 | code | `calculateranking` | ✅ / ❌ | ✅ / ✅ |
| q3 | code | `calculatemonthlymortgage` | ✅ / ✅ | ✅ / ✅ |
| q4 | code | `eliminatedreason,eliminatedhouses` | ✅ / ✅ | ✅ / ❌ |
| q5 | code | `interesttorentratio` | ✅ / ✅ | ✅ / ✅ |
| q6 | db | `ratingdimension,rating_dimension` | ✅ / ✅ | ✅ / ✅ |
| q7 | yml | `datasource` | ✅ / ✅ | ❌ / ❌ |
| q8 | cross | `filterruletype,filter_rule` | ❌ / ✅ | ✅ / ✅ |
| q9 | yml | `aiimportservice,gemini` | ✅ / ✅ | ✅ / ✅ |
| q10 | db | `member` | ✅ / ✅ | ✅ / ✅ |

## 關鍵:兩引擎在 zh/en 出現差異的題目
- q2 [en] grep 勝(expected=`calculateranking`)
- q4 [en] semantic 勝(expected=`eliminatedreason,eliminatedhouses`)
- q7 [zh] semantic 勝(expected=`datasource`)
- q7 [en] semantic 勝(expected=`datasource`)
- q8 [zh] grep 勝(expected=`filterruletype,filter_rule`)

