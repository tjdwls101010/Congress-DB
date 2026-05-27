# Data Completeness Follow-up

This report classifies the data quality signals surfaced by the 10% sanity check.
It separates safe fixes from expected calibration artifacts and unsafe automatic mapping.

## Metrics

| Metric | Value | Interpretation |
| --- | ---: | --- |
| `members_missing_party` | 12 | Referenced member stubs preserved by FK policy; profile metadata is absent. |
| `member_stubs_with_vote_party` | 9 | Point-in-time vote party exists, but it is not the same as profile party. |
| `bill_metadata_gaps` | 164 | Bills missing proposed date or summary. |
| `vote_created_bill_metadata_gaps` | 158 | Metadata gaps attached to bills already touched by votes ingest. |
| `bills_missing_summary` | 164 | Bills whose summary cannot yet participate in keyword search. |
| `unmapped_member_titled_utterances` | 3223 | Utterances with member-like title but no safe member FK in current members table. |
| `safe_utterance_mapping_candidates` | 0 | Rows that can be auto-mapped by unique member name. Current sample should stay zero. |

## Conclusions

- Do not backfill `members.poly_nm` from `votes.poly_nm_at_vote` in this slice; vote party is point-in-time data, while `members.poly_nm` is profile metadata.
- Vote-created bill references are expected during 10% calibration because the votes slice can touch bills outside the 10% bill-list slice; full bill load should enrich them.
- No unique member reference exists for sampled unmapped member-titled utterances, so the ingest path should not fabricate `speaker_mona_cd` values.
- Keep these metrics visible in the sanity report until they are either resolved by full load or explicitly accepted for Supabase migration.

## Missing Party Member Stubs

| name | mona_cd | latest_vote_party | utterances | votes | lead_bills | co_bills | classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 추미애 | URV1689Q | 더불어민주당 | 4104 | 44 | 2 | 22 | referenced_member_stub |
| 민형배 | VRY5522V | 더불어민주당 | 1890 | 44 | 1 | 44 | referenced_member_stub |
| 위성곤 | RQQ3807K | 더불어민주당 | 1408 | 44 | 8 | 21 | referenced_member_stub |
| 양문석 | 3OQ8273H |  | 1404 | 0 | 4 | 22 | referenced_member_stub |
| 박찬대 | BT62420K | 더불어민주당 | 1384 | 44 | 1 | 17 | referenced_member_stub |
| 정을호 | NA61091D |  | 1144 | 0 | 0 | 9 | referenced_member_stub |
| 전재수 | 9YO73104 | 더불어민주당 | 1033 | 44 | 3 | 1 | referenced_member_stub |
| 이원택 | DAV7257X | 더불어민주당 | 913 | 44 | 5 | 43 | referenced_member_stub |
| 김상욱 | VDN5593C | 더불어민주당 | 624 | 44 | 1 | 7 | referenced_member_stub |
| 박수현 | 5TQ6306B | 더불어민주당 | 396 | 44 | 3 | 52 | referenced_member_stub |
| 강훈식 | TRE2429O |  | 247 | 0 | 0 | 1 | referenced_member_stub |
| 추경호 | G152611B | 국민의힘 | 242 | 44 | 0 | 7 | referenced_member_stub |

## Vote-created Bill Metadata Gaps

| bill_no | bill_name | has_votes | missing_fields | classification |
| --- | --- | --- | --- | --- |
| 2218872 | 항공안전법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218871 | 항공보안법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218870 | 철도안전법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218869 | 특정건축물 정리에 관한 특별조치법안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218866 | 공익사업을 위한 토지 등의 취득 및 보상에 관한 법률 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218860 | 자동차관리법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218859 | 농촌공간 재구조화 및 재생지원에 관한 법률 일부개정법률안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218856 | 부동산 거래신고 등에 관한 법률 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218853 | 물의 재이용 촉진 및 지원에 관한 법률 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218852 | 도시교통정비 촉진법 일부개정법률안(대안)(국토교통위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218851 | 야생생물 보호 및 관리에 관한 법률 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218849 | 전기·전자제품 및 자동차의 자원순환에 관한 법률 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218848 | 환경기술 및 환경산업 지원법 일부개정법률안(대안)(기후에너지환경노동위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218847 | 농어촌 빈집 정비 및 관리에 관한 특별법안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218846 | 해운법 일부개정법률안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218845 | 의료법 일부개정법률안(대안)(보건복지위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218844 | 북극항로 활용 촉진 및 연관산업 육성에 관한 특별법안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218842 | 농지법 일부개정법률안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218841 | 지속가능한 연근해어업 발전법안(대안)(농림축산식품해양수산위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |
| 2218840 | 국가연구데이터 관리 및 활용 촉진에 관한 법률안(대안)(과학기술정보방송통신위원장) | true | propose_dt, summary | vote_created_bill_stub_until_full_bill_load |

## Unmapped Member-titled Speakers

| speaker_name | utterances | member_name_matches | classification |
| --- | --- | --- | --- |
| 이병진 | 1140 | 0 | no_member_reference |
| 강유정 | 796 | 0 | no_member_reference |
| 신영대 | 476 | 0 | no_member_reference |
| 조국 | 291 | 0 | no_member_reference |
| 인요한 | 211 | 0 | no_member_reference |
| 임광현 | 186 | 0 | no_member_reference |
| 위성락 | 85 | 0 | no_member_reference |
| 이재명 | 37 | 0 | no_member_reference |
| 박상민 | 1 | 0 | no_member_reference |
