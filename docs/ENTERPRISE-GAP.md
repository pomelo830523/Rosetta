# ENTERPRISE-GAP (Phase 7)

> **定位**:本系統是每個團隊建置一台唯讀 MCP server，集中串接多個 AP
> 單台的合理上限是**百萬行以內**(數個中大型 AP 之和)。
>
> 對象:把現行 KB(驗證場域 BestHouse,約 4.4k 行)外推到**單台百萬行以內**。
> 擴充 SPEC §4.5 規模矩陣與 §8。
>
> **信心等級**(每格必標):
> - **實測** = 本機/本 repo 實際跑出的數字。
> - **試算** = 以實測單位成本做算術外推(算式附上)。
> - **推測** = 工程判斷,無我方實測,標明假設。

---

## 0. 實測基準(所有外推的錨點)

| 項目 | besthouse | 3 AP 合計 | 單位成本 | 信心 |
|---|---|---|---|---|
| symbols | 703 | 1,255 | — | 實測(meta.jsonl 行數) |
| 索引對象 LOC | 4,447 | — | **6.3 行/symbol** | 實測(69 檔 .java/.ts) |
| 向量檔 vectors.npy | 2.75 MB | 5.5 MB(.semantic 全) | **4.0 KB/symbol**(1024 維 × float32) | 實測 |
| codegraph.db | 4.0 MB | 6.75 MB | **5.8 KB/symbol** | 實測 |
| e5-large 首建嵌入 | ~243 s / 703 | — | **0.35 s/symbol**(CPU 單機) | 實測(eval/RESULT.md) |
| MiniLM 首建嵌入 | ~15 s | — | **0.021 s/symbol**(快 15×) | 實測(eval/RESULT.md) |
| 查詢延遲(numpy 暴力內積) | < 1 ms | — | O(N),記憶體頻寬界限 | 實測(SPEC §4.2) |

**目標規模換算**:百萬行 ÷ (10~20 行/symbol) = **5 萬 ~ 10 萬 symbols**。
(BestHouse 6.3 行/symbol 偏密,是 entity/DTO 小樣本;企業後端邏輯較厚,取 10~20 較實。)
以下規劃上限取 **10 萬 symbols**。

---

## 1. 引擎在「百萬行以內」是否夠用(核心結論)

| 面向 | 現行引擎 | 10 萬 symbols 表現 | 夠用? | 信心 |
|---|---|---|---|---|
| 語意向量庫 | numpy 單檔暴力內積 | 每查讀 400 MB 向量 → **~40~100 ms**,單台團隊 QPS 低,無虞 | ✅ 現行直接用 | 試算(單價實測) |
| 向量精度 | float32(4 KB/symbol) | 10 萬 × 4 KB = **400 MB** 常駐,單機無壓力 | ✅ 不需量化 | 試算 |
| 嵌入運算 | CPU 單機 fastembed | 首建:e5 ~9.7 h(一次性)/ MiniLM ~35 min;增量秒級 | ⚠ 首建慢,見 §2 | 試算 |
| 結構圖(建置) | codegraph(tree-sitter) | 任意行數可建;10 萬 symbol → SQLite ~580 MB | ✅ | 試算 |
| 結構圖(邊正確性) | tree-sitter 語法層 | 抓不到 Spring DI / interface / 反射邊 | ⚠ 正確性議題,與規模無關 | 實測(SPEC §4.3) |
| 索引更新 | 排程 + content-hash 增量 | 每 commit 重寫 400 MB vectors.npy → **~1~3 s**,可接受 | ✅ | 試算 |
| config / DB 查詢 | 直讀 yml + MariaDB(唯讀) | 與行數**脫鉤**,任意規模即時讀現值 | ✅ | 實測 |

**判讀**:在百萬行以內的定位下,**現行架構基本不用改**——
numpy 暴力內積、float32、全檔重寫增量在 10 萬 symbol 都落在可接受區間。
唯一實質摩擦是 **e5-large 的 CPU 首建時間**(§2),用 MiniLM 或偶爾借 GPU 即可解。
結構圖換 SCIP-Java 是**邊的正確性**議題(補 DI/反射邊),不是規模議題,與百萬行無關。

---

## 2. 百萬行索引成本外推(10 萬 symbols)

### 2.1 首建時間(試算,單價來自 §0 實測)

| 方案 | 算式(10 萬 symbols) | 時間 | 判定 | 信心 |
|---|---|---|---|---|
| e5-large,CPU 單機 | 100k × 0.35 s | **~9.7 小時** | ⚠ 一次性冷啟,可過夜跑 | 試算 |
| MiniLM,CPU 單機 | 100k × 0.021 s | **~35 分鐘** | ✅ 建議冷啟用 | 試算 |
| e5-large,GPU 批次 | 假設 800~1500 symbol/s | **~1~2 分鐘** | ✅ 有 GPU 時最佳 | 推測(硬體吞吐假設) |

**結論**:首建是唯一痛點,且**只痛一次**。建議:冷啟用 MiniLM 或借一次 GPU,
之後靠增量維持;若堅持 e5-large 品質又無 GPU,過夜首建一次即可。

### 2.2 增量延遲(試算)

- content-hash 只重嵌變更檔:一個 commit 約 5~15 檔 ≈ 100~300 symbols。
  重嵌 300 × 0.35 s(CPU e5)≈ 105 s,MiniLM ≈ 6 s,GPU < 1 s。**試算**
- vectors.npy 全檔重寫:10 萬 × 4 KB = **400 MB**,SSD 順寫 ~1~3 s。→ 在百萬行內**可接受**,
  不需為此換向量庫。(此項在千萬行才會惡化成瓶頸,見 §6。)**試算**

### 2.3 向量記憶體(試算)

| 精度 | 5 萬 symbols | 10 萬 symbols | 信心 |
|---|---|---|---|
| float32(現行) | 200 MB | 400 MB | 試算 |
| int8(範圍外選配) | 50 MB | 100 MB | 試算 |

**結論**:float32 現行即可,單機常駐 < 0.5 GB,**不需量化**。

### 2.4 分片

**不需要**。單台團隊、百萬行內、低 QPS,垂直單機即可。
(分片是千萬行/高並發才觸發的槓桿,列於 §6。)

---

## 3. glossary 成本攤平

| 項目 | 數字 | 信心 |
|---|---|---|
| 現行 besthouse | 31 條 term(SPEC 目標 20~30) | 實測 |
| 產生方式 | `extract_glossary.py` 出骨架 → 人工補缺 | 實測(SPEC §4.1) |
| N 個 AP 成本 | 線性:N × 20~30 條,**一次性**為主 | 試算 |
| 維護頻率 | 只在 DB schema rename / 新業務詞時動 | 推測 |

**判讀**:glossary 只存**名詞對應**不存公式(公式讓 AI 讀 code,不會過期),
是「一次建、少維護」的一次性成本。一隊的 AP 數有限(個位數~十來個),
`extract_glossary.py` 從 entity/enum 抽骨架可自動化 ~60~70%,剩餘為業務口語 alias 人工補充。
**不是瓶頸**;隨 AP 數線性、單位小、且不隨行數成長。
可選自動化:從 commit message / PR 標題挖 zh 業務詞候選。

---

## 4. 回傳最佳化(回傳大小 vs token vs 遵守率)

| 面向 | 現況 | 信心 |
|---|---|---|
| search_code 單次回傳 | top_k 命中的 verbatim 原文 + 檔名:行號(+ 可選一層呼叫鏈) | 實測 |
| 附掛開關 | `include_call_chain`(預設開)已可關,省一層呼叫鏈輸出 | 實測(工具參數) |
| instructions 遵守率 | Phase 5 端到端 zh **10/10**、六條 instructions 無違反 | 實測(eval/ACCEPTANCE.md) |

**觀察與建議**:
- 回傳以 verbatim 原文為主,token 隨 `top_k` 與命中片段大小線性;
  BestHouse 實測單題 top-3 約數百~數千 token,對 context window 無壓力。**實測**
- `include_call_chain` 預設開有助跨源題正確率(Phase 5 已驗),每命中多一層輸出;
  批量/探索式查詢可由 Claude 關掉省 token,現行預設合理。**實測 + 推測**
- 遵守率已飽和(10/10),回傳最佳化應**往省 token 方向調**而非加料;
  命中大方法時可加**回傳字元上限 + 截斷標記**,讓 Claude 需要時再 `read_source` 取全文。**推測**

---

## 5. 一句話總結(本定位)

**百萬行以內,現行架構基本不用動。** numpy 暴力內積 + float32 + 全檔重寫增量
在 10 萬 symbol 都落在可接受區間;唯一摩擦是 e5-large 的 CPU 首建(~9.7 h,一次性),
用 MiniLM(~35 min)或借一次 GPU 即解。config/DB 唯讀查詢與行數脫鉤,glossary 是線性小成本。
結構圖換 SCIP-Java 是為邊的正確性,與規模無關。

---

## 6. 範圍外參考:若單台真要上千萬行 / 跨團隊聚合

以下**不在本產品定位內**,僅備未來評估。此時才需要:

| 槓桿 | 觸發點 | 換成 | 信心 |
|---|---|---|---|
| ANN 向量庫 | > ~10 萬 symbols 或高並發 | hnswlib / Qdrant(HNSW,查詢 O(log N)) | 推測(lib benchmark) |
| int8 量化 | 向量常駐 > 單機記憶體預算 | int8(記憶體 1/4,~1 GB/百萬 symbol) | 試算 |
| GPU 批次嵌入 | 首建 symbol 數使 CPU 時間不可忍 | GPU 批次 | 推測 |
| 向量庫 upsert | 全檔重寫的 vectors.npy 進 GB 級(千萬行) | Qdrant/hnswlib 就地更新 | 推測 |
| 水平分片 | 數千萬 symbol 或多 repo 隔離 | 按 AP/repo 切,查詢層 fan-out 合併 | 推測 |
| SCIP-Java / Spoon | 需要可信的影響範圍(DI/反射邊) | 型別感知 indexer | 推測 |

> 未實測項(超出本定位,需專案驗證):GPU 嵌入吞吐、HNSW 百萬 symbol p95、
> int8 召回損失、Oracle driver。
