# Data Completeness Follow-up

This report classifies the data quality signals surfaced by the current local backfill.
It separates source metadata gaps, safe fixes, and unsafe automatic mapping.

## Metrics

| Metric | Value | Interpretation |
| --- | ---: | --- |
| `members_missing_party` | 20 | Referenced member stubs preserved by FK policy; profile metadata is absent. |
| `member_stubs_with_vote_party` | 20 | Point-in-time vote party exists, but it is not the same as profile party. |
| `bill_metadata_gaps` | 1068 | Bills missing proposed date or summary. |
| `vote_created_bill_metadata_gaps` | 1028 | Metadata gaps attached to bills already touched by votes ingest. |
| `bills_missing_summary` | 1068 | Bills whose summary cannot yet participate in keyword search. |
| `unmapped_member_titled_utterances` | 9 | Utterances with member-like title but no safe member FK in current members table. |
| `safe_utterance_mapping_candidates` | 0 | Rows that can be auto-mapped by unique member name. Current sample should stay zero. |

## Conclusions

- Do not backfill `members.poly_nm` from `votes.poly_nm_at_vote` in this slice; vote party is point-in-time data, while `members.poly_nm` is profile metadata.
- 1028 vote-created bill rows still lack source proposal date and summary after full backfill; keep them as accepted source metadata gaps for migration unless a new source endpoint is added.
- 40 non-vote bill rows still lack source summary after full backfill; they affect summary-search recall, not relational integrity.
- No unique member reference exists for sampled unmapped member-titled utterances, so the ingest path should not fabricate `speaker_mona_cd` values.
- Keep these metrics visible through Supabase migration so accepted source gaps do not get mistaken for ingest failures.

## Missing Party Member Stubs

| name | mona_cd | latest_vote_party | utterances | votes | lead_bills | co_bills | classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 추미애 | URV1689Q | 더불어민주당 | 7982 | 1479 | 29 | 517 | referenced_member_stub |
| 민형배 | VRY5522V | 더불어민주당 | 6919 | 1479 | 240 | 1151 | referenced_member_stub |
| 위성곤 | RQQ3807K | 더불어민주당 | 6068 | 1479 | 102 | 997 | referenced_member_stub |
| 이원택 | DAV7257X | 더불어민주당 | 3536 | 1479 | 73 | 801 | referenced_member_stub |
| 박찬대 | BT62420K | 더불어민주당 | 2619 | 1479 | 24 | 126 | referenced_member_stub |
| 양문석 | 3OQ8273H | 더불어민주당 | 2513 | 1233 | 28 | 460 | referenced_member_stub |
| 이병진 | HFV52269 | 더불어민주당 | 2229 | 1056 | 89 | 1464 | referenced_member_stub |
| 정을호 | NA61091D | 더불어민주당 | 2009 | 1233 | 62 | 459 | referenced_member_stub |
| 박수현 | 5TQ6306B | 더불어민주당 | 1991 | 1479 | 49 | 858 | referenced_member_stub |
| 전재수 | 9YO73104 | 더불어민주당 | 1641 | 1479 | 34 | 339 | referenced_member_stub |
| 김상욱 | VDN5593C | 더불어민주당 | 1609 | 1479 | 32 | 362 | referenced_member_stub |
| 강유정 | Q129715Y | 더불어민주당 | 1396 | 669 | 33 | 483 | referenced_member_stub |
| 신영대 | AFH96856 | 더불어민주당 | 1157 | 1056 | 53 | 515 | referenced_member_stub |
| 임광현 | CST4991F | 더불어민주당 | 630 | 716 | 37 | 297 | referenced_member_stub |
| 조국 | T3E4932G | 조국혁신당 | 564 | 281 | 10 | 569 | referenced_member_stub |
| 강훈식 | TRE2429O | 더불어민주당 | 503 | 669 | 24 | 260 | referenced_member_stub |
| 인요한 | B7789327 | 국민의힘 | 409 | 1056 | 20 | 573 | referenced_member_stub |
| 추경호 | G152611B | 국민의힘 | 288 | 1479 | 36 | 299 | referenced_member_stub |
| 위성락 | T9E37304 | 더불어민주당 | 245 | 669 | 10 | 178 | referenced_member_stub |
| 이재명 | IUD9392R | 더불어민주당 | 89 | 669 | 4 | 16 | referenced_member_stub |

## Bill Metadata Gaps

| bill_no | bill_name | has_votes | missing_fields | classification |
| --- | --- | --- | --- | --- |
| 2218872 | 항공안전법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218871 | 항공보안법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218870 | 철도안전법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218869 | 특정건축물 정리에 관한 특별조치법안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218866 | 공익사업을 위한 토지 등의 취득 및 보상에 관한 법률 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218860 | 자동차관리법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218859 | 농촌공간 재구조화 및 재생지원에 관한 법률 일부개정법률안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218856 | 부동산 거래신고 등에 관한 법률 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218853 | 물의 재이용 촉진 및 지원에 관한 법률 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218852 | 도시교통정비 촉진법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218851 | 야생생물 보호 및 관리에 관한 법률 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218849 | 전기·전자제품 및 자동차의 자원순환에 관한 법률 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218848 | 환경기술 및 환경산업 지원법 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218847 | 농어촌 빈집 정비 및 관리에 관한 특별법안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218846 | 해운법 일부개정법률안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218845 | 의료법 일부개정법률안(대안)(보건복지위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218844 | 북극항로 활용 촉진 및 연관산업 육성에 관한 특별법안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218842 | 농지법 일부개정법률안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218841 | 지속가능한 연근해어업 발전법안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |
| 2218840 | 국가연구데이터 관리 및 활용 촉진에 관한 법률안(대안)(과학기술정보방송통신위원장) | true | propose_dt, summary | vote_created_source_metadata_gap_after_full_backfill |

## Unmapped Member-titled Speakers

| speaker_name | utterances | member_name_matches | classification |
| --- | --- | --- | --- |
| 전종득 | 5 | 0 | no_member_reference |
| 기왕 | 1 | 0 | no_member_reference |
| 김상휘 | 1 | 0 | no_member_reference |
| 깅대식 | 1 | 0 | no_member_reference |
| 박상민 | 1 | 0 | no_member_reference |
