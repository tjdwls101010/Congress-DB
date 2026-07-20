# 보안 정책

## 먼저 — 공개된 연결문자열은 취약점이 아닙니다

이 저장소에는 Postgres 연결문자열이 **비밀번호까지 평문으로** 들어 있습니다(`README.md`, `docs/wiki/`, `.github/workflows/freshness-watchdog.yml`). 자동 스캐너가 이걸 유출 자격증명으로 잡을 수 있지만, **의도된 공개 read-key입니다.**

```
postgresql://congress_ro:...@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress
```

- `congress_ro` 역할에는 **`SELECT`와 검색 함수 `EXECUTE`만** 부여돼 있습니다. `INSERT`·`UPDATE`·`DELETE`·DDL은 권한 자체가 없습니다.
- 노출 대상은 소비자 객체 11개(테이블 7·뷰 2·함수 2)뿐이고, 내부 적재·운영 테이블과 ETL raw 테이블은 REVOKE돼 있습니다.
- 데이터는 전부 **공개 입법 사실**이며 개인정보 컬럼은 제거됐습니다.
- 남용 대비로 `statement_timeout = 60초` 상한이 걸려 있습니다.

배경은 [`docs/design/DECISIONS.md`](docs/design/DECISIONS.md)의 2026-06-18 항목과 [`docs/design/DB-ACCESS.md`](docs/design/DB-ACCESS.md)를 참고하세요.

**다만 이 계정으로 실제 쓰기가 되거나, 아래 표의 "차단됨" 객체가 조회된다면 그건 진짜 취약점입니다** — 아래 절차로 제보해 주세요.

## 무엇이 비밀이고 무엇이 아닌가

| 값 | 비밀인가 | 비고 |
| --- | --- | --- |
| `CONGRESS_RO_URL` (읽기전용) | **아니오** | 의도적 공개. 위 참조 |
| `.neon` (Neon project id) | **아니오** | 식별자일 뿐. CI·clone에서 필요해 커밋됨 |
| `DATABASE_URL` / `CONGRESS_MAIN_URL` (owner) | **예** | 쓰기 권한. `.env.local`(gitignored) |
| `NEON_API_KEY` | **예** | 컨트롤플레인 — 브랜치 생성·복원 권한 |
| `NATIONAL_ASSEMBLY_API_KEY` | **예** | 국회 OpenAPI 키 |

`.env`와 `.env.local`은 `.gitignore`에 있습니다. **커밋 전에 이 두 파일이 스테이지에 없는지 확인하세요.**

### `congress_ro`가 접근할 수 없어야 하는 것

이것들이 읽기전용 계정으로 조회된다면 권한 설정이 깨진 것입니다.

- `ingest_runs` · `ingest_cursors` · `dead_letters` — 운영 테이블
- `bill_relations` · `bill_source_aliases` — ETL 내부 테이블 (소비자는 `bill_lineage` 뷰로 읽습니다)

`db/roles/congress_ro.sql`을 owner 연결로 재실행하면 allowlist가 복구됩니다(멱등). `tests/test_congress_ro_role.py`가 이 계약을 정적으로 검증합니다.

### 알려진 회귀 — RLS 자동 재활성화

Neon Data API나 Neon Auth 설정을 만지면 **소비자 테이블에 RLS가 정책 없이 자동으로 다시 켜지는** 일이 있습니다. 이 경우 owner는 테이블 소유자라 정상으로 보이지만 `congress_ro`와 익명 접근은 **모든 테이블을 0행으로** 봅니다(뷰는 소유자 권한으로 실행돼 정상 반환하니 더 헷갈립니다).

이건 데이터 유출이 아니라 가용성 문제이지만, 조용히 일어나므로 알아둘 가치가 있습니다.

- 탐지: `make regression-pack` (실패 시 종료코드 1)
- 복구: `db/roles/data_api_public_read.sql`을 owner 연결로 재실행

## 취약점 제보

**공개 이슈로 올리지 마세요.** GitHub의 비공개 제보 경로를 사용해 주세요.

1. 이 저장소의 **Security** 탭으로 이동
2. **Report a vulnerability** 클릭
3. 재현 절차와 영향 범위를 적어 제출

제보에 포함하면 좋은 것: 무엇을 시도했는지, 어떤 자격증명·엔드포인트를 썼는지, 관찰된 결과와 기대했던 결과.

보안과 무관한 데이터 오류·문서 오류는 일반 [GitHub Issues](https://github.com/tjdwls101010/Congress-DB/issues)로 올려 주시면 됩니다.

## 대응

이 프로젝트는 개인이 유지보수합니다. 상업적 SLA는 없지만, 유효한 제보에는 확인 회신을 드리고 심각도에 따라 조치합니다.

- **owner 자격증명 노출, 쓰기 권한 우회** — 즉시 자격증명 회전 후 조치
- **차단 대상 객체 노출** — 권한 스크립트 재적용
- **`congress_ro` 남용·과부하** — 비밀번호 회전을 검토합니다. 다만 이건 공개 키라 회전하면 모든 소비자가 새 문자열로 갱신해야 하므로 비용이 큽니다

## 범위 밖

- 이 DB가 담은 **데이터 자체의 오류·결측** — 취약점이 아니라 원천 데이터 이슈입니다. [함정과 경계](docs/wiki/04-gotchas-and-limits.md)를 먼저 확인하고, 그래도 이상하면 일반 이슈로 올려 주세요.
- **Neon 플랫폼 자체의 취약점** — [Neon](https://neon.tech)에 직접 제보해 주세요.
- **열린국회정보 OpenAPI의 취약점** — 국회사무처 소관입니다.
