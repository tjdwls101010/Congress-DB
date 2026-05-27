# Session Group Agent Review

This is an agent-led semantic review of the current 10% `session_groups` load. The goal is not to force a brittle 100% rule set, but to decide whether the current Q&A grouping is good enough as a high-precision meaning unit and how recall should be handled without weakening that unit.

## Review Rubric

- **Correct**: the group has the intended questioner, a real respondent, and the range is mostly one Q&A meaning unit.
- **Borderline**: the intended questioner and respondent are right, but the range includes procedural noise or starts a few utterances early.
- **Incorrect**: the group is procedural noise, the wrong member is treated as questioner, or it is not a Q&A meaning unit.
- **Missing**: an ungrouped member turn is followed by a real non-member response and appears to be a Q&A meaning unit.

## Objective Checks

- Total groups: 17,339
- Groups with no detected respondents: 0
- 본회의/소위원회 groups: 0
- Integrity errors in `validate-session-groups`: 0
- Semantic review candidates: 2,659 groups with 50+ utterances, 312 groups with 100+ utterances, largest group 266 utterances

## Risk Signal Counts

Across all generated groups:

| Type | Groups | Short <=5 | Long >=50 | Long >=100 | Delayed questioner >=5 | Short questioner text <=20 | Suspicious phrase |
|---|---:|---:|---:|---:|---:|---:|---:|
| 국정감사 | 12,909 | 459 | 1,903 | 215 | 63 | 1,095 | 456 |
| 국정조사 | 1,018 | 20 | 339 | 58 | 7 | 156 | 38 |
| 상임위 | 422 | 16 | 78 | 14 | 6 | 37 | 25 |
| 인사청문회 | 2,865 | 134 | 318 | 24 | 16 | 292 | 116 |
| 특별위 | 125 | 4 | 21 | 1 | 3 | 12 | 3 |

In the 20-meeting evaluation sample:

| Type | Groups | Short <=5 | Long >=50 | Long >=100 | Delayed questioner >=5 | Short questioner text <=20 | Suspicious phrase |
|---|---:|---:|---:|---:|---:|---:|---:|
| 국정감사 | 208 | 5 | 34 | 4 | 1 | 19 | 11 |
| 국정조사 | 296 | 7 | 107 | 30 | 1 | 61 | 11 |
| 상임위 | 81 | 7 | 8 | 0 | 0 | 6 | 4 |
| 인사청문회 | 234 | 8 | 26 | 1 | 0 | 25 | 9 |

## Read Samples

| Group | Judgment | Evidence |
|---:|---|---|
| 106128 | Correct | Chair calls 이재강; 이재강 questions 통일부장관; responses follow in sequence. |
| 106261 | Correct | Chair identifies 전용기; 전용기 calls 김성태 증인 and conducts Q&A. |
| 115295 | Correct | Long multi-witness 국정조사 group; 한기호 questions several witnesses in a coherent examination block. |
| 107338 | Correct | Long 국감 group; 박충권 questions 정무수석/비서실장. Length is high but still one Q&A block. |
| 106420 | Correct | Short greeting starts the block, but 정일영 immediately continues policy questions to the nominee. |
| 106525 | Correct | First utterance is just "조국혁신당입니다", but the same member immediately starts witness Q&A. |
| 106505 | Borderline | The group starts with time-allocation chatter, then 이주희 conducts a short Q&A. Questioner is right, start is early. |
| 106141 | Borderline/Incorrect | This is an 의사진행발언 asking the minister to cover a topic. It has a response, but it is procedural rather than a normal Q&A group. |
| 107343 | Incorrect | Chair asks 주진우 to sit while 전용기's Q&A is still continuing; the detector incorrectly starts a 주진우 group. |
| 117131 | Incorrect | Chair-led fact check around a profanity quote; 노종면's "열여덟" is not a new Q&A meaning unit. |

## Recall Findings

The main weakness is not empty/no-respondent over-detection anymore. It is recall in chaotic meetings where the chair does not cleanly call the next questioner.

Concrete missed examples from meeting `55734`:

- `김은혜` at sequences 269, 271, 273, 275, 279, 281, 283: real Q&A with the National Human Rights Commission chair, but no `session_group_id`.
- `박상혁` at sequences 287, 289, 295, 297, 303, 305, 311, 313, 315, 317, 319, 321, 323, 325, 327, 329, 331, 333, 335, 337, 339, 341, 343: real Q&A/pressing questions, but ungrouped.
- `강선영` at sequences 346, 348, 350, 352, 354, 356: real Q&A-like policy questioning, but ungrouped.

Proxy count for possible missed Q&A starts across all currently loaded applicable meetings:

| Type | Orphan Q&A start proxy | Meetings affected |
|---|---:|---:|
| 국정감사 | 1,330 | 225 |
| 국정조사 | 68 | 18 |
| 상임위 | 45 | 16 |
| 인사청문회 | 187 | 45 |

This proxy overcounts because one real Q&A can contain many member utterances, but it proves recall loss is real enough to track.

## Conclusion

The current detector is good as a **high-precision Q&A group generator** for clean chair-call patterns. It should not be expanded with sentence-specific exclusions such as "질의 시간 안 줄 겁니다"; that would create a brittle rule list.

Do **not** add a separate **orphan Q&A candidate** layer in the current plan. It would add a new module and review surface before we have proved that the API/SDK search experience needs it.

The current search strategy should be:

1. Use `session_groups` first for high-confidence grouped Q&A.
2. Use `utterances` keyword/FTS search for recall.
3. When an ungrouped utterance matches, read nearby rows by `meeting_id` + `sequence` window so the caller can recover the local context.
4. Reconsider an orphan candidate layer only after the planned search-quality evaluation shows repeated important misses that this fallback cannot handle.

This keeps `session_groups` reliable as an API/SDK meaning unit while avoiding premature complexity. The trade-off is explicit: "all Q&A by a member" will not be perfectly complete through `session_groups` alone, but the combined session-first + utterance-fallback flow should provide a higher-value 90% solution before we spend disproportionate effort chasing the remaining edge cases.
