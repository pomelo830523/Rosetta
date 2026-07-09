# FLEET-EVAL — 50 AP / 百萬行:逐 AP 決定 grep | semantic | auto

> 目的:在真實艦隊(~50 AP、合計百萬行)上,用**數字**決定每個 AP 該不該建語意索引。
> 前提結論(eval/ABLATION.md、code-vs-codegraph 兩輪):**命名尚可 + 有維護 glossary 時,
> grep / semantic / codegraph-名稱 三者品質收斂**。所以到艦隊規模,決策重心從「品質」
> 移到「**延遲 + 建置成本**」,且必須**逐 AP**判定。

## 決策其實是「逐 AP 二選一」

`grep | semantic | auto` 拆成兩層:

1. **要不要為這個 AP 維護語意索引?**(真正有成本的取捨)
2. 若要 → 部署成 **`auto`**(推薦:重建/損壞自動墊 grep,不報錯)或 **`semantic`**(嚴格)。
   若不要 → **`grep`**。

本實驗對每個 AP 產出二元判定:**build semantic index or not**。

## 四組指標(逐 AP)

| 組 | 指標 | 免標註? | 工具 |
|---|---|---|---|
| A 規模 | LOC、symbol 數 | 是 | fleet_eval.py |
| B 延遲 | grep / semantic 查詢 p50/p95/max、model 冷載 | 是 | fleet_eval.py |
| C 建置成本 | 首建時間、記憶體(symbols×dim×4B)、磁碟 | 是 | fleet_eval.py（`--build` 實測，否則試算） |
| D① 分歧度 | grep/semantic top-k 重疊(Jaccard、top-1 一致) | 是（品質探針） | fleet_eval.py |
| D② 命中率 | grep vs semantic top-k 命中 | **否（要標註）** | eval_ablation.py |
| D 命名 | 拆詞中位數、opaque 佔比、註解覆蓋 | 是 | fleet_eval.py |

**核心技巧**:用 D①「分歧度」當免標註探針,只對分歧大的 AP 才做昂貴的 D② 標註,把人工成本壓到 ~10~20% 的 AP。

## 三層流程

```
Tier 1  全 50 AP · 全自動   →  fleet_eval.py            → eval/FLEET-REPORT.md
Tier 2  套決策規則 · 標記不確定的 AP(報告內「待 Tier 3」)
Tier 3  只對被標記 AP · 人工標註 10~30 題 → eval_ablation.py → eval/ABLATION-<app>.md
```

## 決策規則(逐 AP,門檻見 fleet_eval.py 頂部常數)

| # | 條件 | 判定 |
|---|---|---|
| 1 | grep **p95 > 1000ms** | **semantic/auto**(延遲驅動,不看品質) |
| 2 | grep p95 ≤ 1000ms **且** top-k Jaccard ≥ 0.60 **且**命名健康 | **grep**（等價又便宜） |
| 3 | grep 夠快但分歧大 / 命名貧弱 | **待 Tier 3**：eval_ablation.py 標註評測,semantic − grep **≥ +10% 且 ≥ +3 絕對(≥30 題)** → semantic/auto;否則 grep |

- **命名健康** = 拆詞中位數 ≥ 2 **且** opaque 名(單字母/純縮寫/拆不出 2 詞)佔比 < 30%。
- **auto vs semantic**:凡判「要索引」者**預設 `auto`**(索引缺/重建中自動墊 grep,零報錯);
  只有「索引沒建好寧可報錯提醒管理員」才用 `semantic`。

## 全艦隊 rollup(50 AP 的重點)

fleet_eval.py 末段自動加總:幾個 AP 要索引 → **首建合計時間**(能否過夜)、**常駐記憶體**
(∑ symbols×dim×4B,單機預算內?)。若 e5 全量首建超窗 → 大 AP 改 **MiniLM**(快 15×,
`--model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)或借 GPU,再測 C 組。

## 怎麼跑

```powershell
# Tier 1+2:全艦隊自動量測 → eval/FLEET-REPORT.md
.\.venv\Scripts\python.exe -X utf8 scripts\fleet_eval.py --queries 60

#   沒建語意索引的 AP 要先建才能量 semantic 延遲/分歧:
.\.venv\Scripts\python.exe -X utf8 scripts\fleet_eval.py --queries 60 --build-missing

#   要實測(非試算)首建時間:加 --build(很慢,大艦隊慎用,或只對大 AP 跑 --app)
.\.venv\Scripts\python.exe -X utf8 scripts\fleet_eval.py --app <big-app> --build

# Tier 3:對報告標「待 Tier 3」的 AP,先標註 eval/questions-<app>.yaml(格式同 questions.yaml),再:
.\.venv\Scripts\python.exe -X utf8 scripts\eval_ablation.py --app <app> --langs zh,en
```

## 嚴謹性 / 要控制的干擾

- **延遲**:每 AP ≥50 查詢、warm cache、報 p50/p95;**model 冷載單獨報**(fleet_eval 已分離)。
- **品質小樣本**:10 題差 1 題是雜訊;Tier 3 每 AP **≥30 題**或跨 AP pool,並人工抽查。
- **索引新鮮度**:量測前先用當前 fastembed 版本**全量重建**(踩過 e5 CLS→mean pooling 靜默劣化)。
  `fleet_eval.py --build-missing` / `--build` 會 rebuild,已規避。
- **同 glossary、同 top_k、固定亂數種子**(fleet_eval / eval_ablation 皆已內建)。
- grep 延遲本來就隨檔案量增長——**這正是訊號,不要正規化掉**。

## 免標註查詢集怎麼生(fleet_eval.py `build_queries`)

每 AP 自動抽:glossary 的 term/alias(中文業務查詢) + 抽樣 identifier(英文)。
純計時(B)與比對重疊(D①)不需要正解;只有 Tier 3 命中率(D②)需要人工 `expected`。
