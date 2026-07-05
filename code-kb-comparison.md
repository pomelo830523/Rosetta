# 三種 Code KB 方案實測比較（BestHouse）

> 目標：讓人用自然語言查專案的「業務邏輯與公式」。
> 我在 BestHouse 上實際做了三種方案並比較，以下是結論。

---

## 方案一：手動維護 KB 文件（靜態 `.md`）

把每條公式/規則手寫成 markdown 知識條目，MCP 搜尋這些文件。

- **機制**：人工把「不含車位單價 = (折扣後總價 − 車位價) ÷ (建坪 − 車位坪)」抄進 `.md`，附 aliases/keywords 供比對。
- **優點**：答案乾淨、可讀性高、對非工程師友善；中文原生支援；零依賴。
- **缺點**：**會 drift** —— 程式碼改了、文件忘了改，最容易出錯的就是「忘記同步」；只涵蓋你寫過的主題；規模一大維護不動。
- **維護成本**：🔴 高（每次改邏輯都要回頭改文件）
- **適用**：主題少、變動慢、需要給非技術人看的場景。

## 方案二：grep 讀最新程式碼（自寫 MCP）

不存任何文件，每次查詢即時掃原始碼、用大括號配對切出 method、bigram 比對中文註解。

- **機制**：query 進來 → 掃 `.java`/`.ts` → 切 method 區塊 → 中文 bigram + 英文 identifier 評分 → 回最相關 method 原文 → 由 AI 解釋。
- **優點**：**零 KB 維護、不可能 drift**（永遠讀當下的碼）；離線、零外部依賴；**中文查詢可命中**（比對中文註解）。
- **缺點**：只能查「單一 method」；**做不到跨檔/關係查詢**（誰呼叫、影響範圍）；大括號切割是 heuristic，邊界案例會失準；**百萬行不適用**（每次全掃、bigram 精度崩）。
- **維護成本**：🟢 低（改碼後不用動 MCP）
- **適用**：中小專案、查單點邏輯、需要中文 NL、且環境受限不能架服務。

## 方案三：codegraph（語意圖 + FTS）

預先把 codebase 建成 graph（functions/classes/call chains），存 SQLite，透過 MCP 暴露 `explore/callers/callees/impact`。

- **機制**：tree-sitter 解析 → 建圖 → file-watcher 自動增量同步；查詢走預建的圖 + FTS 全文檢索。
- **優點**：**結構查詢精準**（caller/callee/impact/blast-radius）；**跨檔、跨語言**（Java + TS）；100% 本地；可 scale 到大專案；自動同步。
- **缺點**：需建索引（靠 file-watcher 補同步，理論上仍有極短 drift 窗）；**FTS 不吃中文 NL**（實測中文查詢直接 miss）；要做完整中文知識庫仍需疊 embedding 層。
- **維護成本**：🟢 低（自動 sync）
- **適用**：中大型、需要影響分析/重構輔助、跨檔追邏輯。

---

## 對照表

| 維度 | ① 靜態 KB | ② grep | ③ codegraph |
|---|---|---|---|
| KB 維護成本 | 🔴 高 | 🟢 零 | 🟢 低（自動） |
| Drift 風險 | 🔴 高 | 🟢 無 | 🟡 極低 |
| 中文 NL 查詢 | ✅ | ✅ | ❌（FTS 不吃中文） |
| 跨檔/關係查詢 | ❌ | ❌ | ✅ |
| 影響分析 | ❌ | ❌ | ✅ |
| 解析準確度 | —（人工） | 🟡 heuristic | ✅ AST |
| 百萬行可擴展 | ❌ | ❌ | ✅ |
| 外部依賴 | 無 | 無 | 自帶（SQLite，本地） |

---

## PoC 實測重點（BestHouse，77 檔 / 1,234 nodes / 2,014 edges）

- **codegraph 英文查詢 `price per ping without parking`**：一次撈出**同一公式散落在 3 處**——
  後端 `HouseService:321`、後端 `FilterService:302`（重複實作！）、前端 `house-list.component.ts:324`，
  並附 blast-radius + **⚠️ 無測試覆蓋**警告。**這是方案①②都看不到的維護風險。**
- **codegraph 中文查詢 `不含車位單價 計算`**：**No relevant code found**（FTS 不吃中文）。
- **方案② grep 同一中文查詢**：**命中**（靠比對中文註解）。

→ 兩者強弱互補：**codegraph 贏在結構，grep 贏在中文 NL。**

---

## 決策建議

| 情境 | 選擇 |
|---|---|
| 主題少、給非技術人看 | ① 靜態 KB |
| 中小專案、查單點邏輯、要中文、環境受限 | ② grep |
| 中大型、要影響分析/跨檔追蹤 | ③ codegraph |
| **封閉環境 + 百萬行 Java + 中文註解 + 弱模型** | **③ codegraph（結構） + 本地多語 embedding（中文語意）= GraphRAG** |

**核心心法**：模型越弱、codebase 越大，價值就從「模型的腦」轉移到「retrieval 的品質」。
靜態 KB 把賭注押在「人會記得同步」（最不可靠）；grep 押在「即時讀檔」（準但只能查單點）；
codegraph 押在「預建的結構圖」（強在關係，但中文語意要另外補）。

**一句話總結**：沒有單一最佳解 —— 小專案用 grep 就夠、要結構分析上 codegraph、
而真正的企業級中文知識庫是 **codegraph 的圖 ＋ 本地中文 embedding 的向量** 兩者疊加。

---

## 本專案最終採用（實作後的收斂）

實作過程中試到第三層（自建 embedding）後，發現一個關鍵轉折：

- PoC 早期用 **codegraph CLI 的 `explore`** 測中文 → miss，所以一度自建了
  `semantic_search`（fastembed 本地多語 embedding）來補中文語意。
- 但實際在 Claude 裡用 **codegraph 的 MCP 工具**時，中文搜尋已可接受 →
  **不需要再自己維護一層 embedding**（還要管模型下載、離線快取、索引重建）。

於是最終分工簡化為兩個來源、各司其職：

| 角色 | 由誰負責 | 工具 |
|---|---|---|
| 關鍵字 + 中文註解比對、直接讀原始碼原文 | **besthouse-kb**（本 server） | `search_code` / `read_source` |
| 中文語意搜尋、跨檔結構 / 影響分析 | **codegraph 的 MCP** | `explore` / `callers` / `callees` / `impact` |

`semantic_search` 與 `semantic_index.py` 已移除（git 歷史仍可追回）。

**為什麼這樣收斂**：能用現成工具（codegraph）達成的，就不要自己多養一層。
自建 embedding 的維護成本（模型快取、離線設定、重建索引、那次卡 30 分鐘的連網 hang）
在 codegraph 已能處理中文後就不划算了 —— **少一個自己要維護的東西，就少一個會壞的地方。**

> 但前一節的企業級結論仍然成立：若未來面對的是
> **封閉環境 + 百萬行 Java + 弱模型**，且該環境內的 codegraph 中文能力不足，
> 自建（或強化）中文 embedding 層仍是正解。是否要自建，取決於「現成工具夠不夠用」。
