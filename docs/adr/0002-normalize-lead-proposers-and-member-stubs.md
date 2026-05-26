# 0002. 복수 대표발의자와 누락 의원 참조를 정규화한다

법안 API는 `RST_MONA_CD`에 복수 대표발의자를 콤마로 담을 수 있고, 의원 인적사항 API가 반환하지 않는 MONA_CD도 참조한다. FK를 제거하거나 참조를 버리면 "의원 ID로 JOIN"이라는 핵심 가치가 약해지므로, `bill_lead_proposers`를 추가해 대표발의자를 N:M으로 정규화하고 누락 의원은 이름만 가진 `members` stub으로 보존한다.

`bills.rst_mona_cd`는 단일 대표발의일 때의 편의 FK로만 유지하고, 정확한 대표발의 조회의 interface는 `bill_lead_proposers`로 둔다.
