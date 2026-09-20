# CLAUDE.md — tableau_calculation_map

Tableau 워크북(`.twbx`)의 계산식 리니지 맵을 만드는 CLI. 콜드스타트 요약은 `ESSENTIAL.md`, 설계 배경은 `docs/PRD.md`, 구조는 `docs/ARCHITECTURE.md`.

## 작업 시작 전

1. `docs/ARCHITECTURE.md`의 **"함정"** 절을 읽어라. 대부분의 오답이 거기 적혀 있다.
2. 숫자를 바꾸는 작업이면 `test_twbmap.py`를 먼저 보라. 실측값이 픽스처로 고정돼 있다.

## 실행 규칙 (Windows)

```bash
PYTHONUTF8=1 python twbmap.py "<파일.twbx>" --out out/
PYTHONUTF8=1 python test_twbmap.py
```

- `python3`이 아니라 `python`이다. `python3`은 Windows Store 스텁이다
- `PYTHONUTF8=1`을 빼면 한글 출력에서 cp949 `UnicodeEncodeError`가 난다

## DON'T

- **`.twbx` / `.twb` / `.twbr` / `.hyper`를 커밋하지 마라.** 사내 실적 데이터가 내장돼 있다. `.gitignore`에 걸려 있으니 `-f`로 강제 추가하지 마라
  (`.twbr`은 Tableau가 워크북을 열면 남기는 복구 파일이다. 워크북 XML 그대로라 원본과 같은 크기다)
- **사내 필드명·시트명·워크북명을 추적 파일에 적지 마라.** 코드·`CLAUDE.md`·`ESSENTIAL.md`·`docs/`·커밋 메시지 전부 해당한다.
  예시가 필요하면 `계산식 A`·`원본컬럼 X` 같은 가명을 쓴다. 실물은 gitignore된 `descriptions.json`·`fixtures.local.json`·`NOTES.local.md`에만 둔다
- **`git add -A`를 쓰지 마라.** `.gitignore`가 아직 모르는 파일이 딸려 들어온다(2026-09-19 `.twbr`이 그랬다).
  파일을 지정하고 `git diff --cached --name-only`로 확인하라
- **`descriptions.json`의 기존 `desc`를 덮어쓰지 마라.** 없는 키만 추가한다. 이게 깨지면 사람이 쓴 설명이 조용히 사라진다
- **`reviewed: false`인 설명을 확정된 사실처럼 표시하지 마라.** 초안 배지를 유지하라
- **해석 못 한 필드 참조를 추측으로 메우지 마라.** `unresolved`에 넣고 리포트하라
- **워크북을 수정하지 마라.** 이 도구는 읽기 전용이다. 통합·리네임은 제안까지만이다
- **`.hyper`를 열지 마라.** 수십 MB이고 필요도 없다
- 의존성을 추가하지 마라. stdlib으로 다 된다

## DO

- 수식 표시는 4줄 / 240자에서 자른다 (같은 계열 비공개 도구의 카탈로그 렌더러와 같은 규칙)
- 한글 필드명 매칭은 NFC 정규화 + casefold를 거친다
- 근거가 약한 제안은 약하다고 표기하라. 리네임 제안이 그렇다 — 기준 워크북에서 기본이름 잔존은 거의 없었다
- 렌더러를 늘리기 전에 `map.md`로 내용부터 맞춰라. 시각화는 내용이 맞은 뒤의 문제다
- **`twbmap.py`는 단일 파일로 유지한다.** 2026-09-19에 분할하지 않기로 결정했다 — 파이프라인이 선형이라 `parse`/`analyze`/`render`로 갈라도 호출 한 줄씩만 남은 파일이 늘어난다. 줄 수를 트리거로 쓰지 마라

## 이 코드베이스의 함정 (실측으로 확인된 것)

전체 목록은 `docs/ARCHITECTURE.md` 마지막 절에 있다. 가장 자주 틀리는 셋:

1. `<calculation>` 태그 수는 **실제 정의 수의 수십 배**다. 나머지는 시트별 사본이다
2. 파라미터는 `Parameters`라는 **별도 데이터소스**에 있다
3. 파라미터 수식은 상수(`2.`, `FALSE`)라 중복 탐지에서 빼지 않으면 오탐이 쏟아진다

## 커밋

- 커밋과 push는 **사용자가 요청할 때만** 한다
- 이 폴더는 **독립 repo**다 — `Soonyeon-Kim/tableau_calculation_map` (main). 커밋은 이 폴더 안에서 한다
- `main` → `origin/main` 직접 push 한다. 브랜치·PR은 쓰지 않는다
- 커밋 메시지 접두어는 쓰지 마라. repo 이름이 곧 맥락이다
- **스테이징한 파일을 커밋 전에 눈으로 확인하라.** `.twbx`·`.twbr`은 사내 데이터라
  하나만 새어 나가도 끝이다:
  ```bash
  git add <파일들>                      # -A 대신 파일을 지정하라
  git diff --cached --name-only         # 워크북·out/·*.local.*·descriptions.json 이 없는지 확인
  ```
