# 檢索模型評測結果(Phase 3 定案依據)

- corpus:766 symbols(NL 訊號,與 production 索引相同組裝)
- 指標:top-3 命中(production 同款混合排序,含 glossary/identifier boost)
- 限制:SPEC 原候選 bge-m3 不在本版 fastembed 支援清單,未納入;企業選型時應以 onnx 自行掛載補測。

| model | 嵌入耗時 | zh | en | de | ja | 總計 |
|---|---|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 15s | 4/5 | 4/5 | 3/5 | 5/5 | 16/20 |

<details><summary>miss 明細(paraphrase-multilingual-MiniLM-L12-v2)</summary>

  - paraphrase-multilingual-MiniLM-L12-v2 [zh] q2 miss:top1=com.besthouse.entity::houserating
  - paraphrase-multilingual-MiniLM-L12-v2 [en] q4 miss:top1=com.besthouse.service::filterservice::applyfilters
  - paraphrase-multilingual-MiniLM-L12-v2 [de] q1 miss:top1=com.besthouse.dto::housedto::latestregistrypriceperping
  - paraphrase-multilingual-MiniLM-L12-v2 [de] q4 miss:top1=com.besthouse.dto::housedto::builder

</details>
| paraphrase-multilingual-mpnet-base-v2 | 71s | 3/5 | 4/5 | 4/5 | 4/5 | 15/20 |

<details><summary>miss 明細(paraphrase-multilingual-mpnet-base-v2)</summary>

  - paraphrase-multilingual-mpnet-base-v2 [zh] q2 miss:top1=houseratecomponent::house
  - paraphrase-multilingual-mpnet-base-v2 [zh] q4 miss:top1=com.besthouse.dto::applyfilterresultdto::eliminatedhousedto::houseid
  - paraphrase-multilingual-mpnet-base-v2 [en] q4 miss:top1=com.besthouse.dto::applyfilterresultdto::eliminatedhousedto::reason
  - paraphrase-multilingual-mpnet-base-v2 [de] q4 miss:top1=com.besthouse.dto::applyfilterresultdto::eliminatedhousedto::reason
  - paraphrase-multilingual-mpnet-base-v2 [ja] q2 miss:top1=houseratecomponent::dimensions

</details>
| multilingual-e5-large | 243s | 5/5 | 3/5 | 4/5 | 5/5 | 17/20 |

<details><summary>miss 明細(multilingual-e5-large)</summary>

  - multilingual-e5-large [en] q2 miss:top1=houseratecomponent::gethousetotalscore
  - multilingual-e5-large [en] q4 miss:top1=houselistcomponent::applyfilters
  - multilingual-e5-large [de] q4 miss:top1=com.besthouse.controller::housecontroller::applyfilters

</details>
