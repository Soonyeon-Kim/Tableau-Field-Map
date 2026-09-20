# 아키텍처

## 디렉토리 구조

```
tableau_calculation_map/
├── twbmap.py            # 전부: 파싱 → 그래프 → 분석 → 렌더 (단일 파일)
├── template.html        # 단일 파일 SVG 뷰어(외부 라이브러리·CDN 없음). __DATA__에 JSON 주입
├── test_twbmap.py       # assert 기반. 워크북 실측값은 fixtures.local.json(gitignore)
├── descriptions.json    # 필드별 한국어 설명 (Claude 초안 + 사람 검수) — gitignore
├── fixtures.local.json  # 기준 워크북 실측값(테스트 픽스처) — gitignore
├── NOTES.local.md       # 기준 워크북에 대해 알아낸 것 — gitignore
├── docs/
│   ├── PRD.md           # 무엇을·왜
│   └── ARCHITECTURE.md  # 이 파일 — 어떻게
├── README.md            # 공개 저장소 첫 화면
├── LICENSE              # MIT
├── CLAUDE.md            # 작업 규칙 (본문)
├── ESSENTIAL.md         # 콜드스타트 5분 요약 · 인수인계용
├── .gitignore           # 워크북·descriptions.json·*.local.*·out/·map.* — 사내 이름 유출 차단
└── out/                 # map.json / map.md / map.html (gitignore)
```

모듈을 쪼개지 않는다. 파이프라인이 `parse → analyze → render` 한 방향 직선이라 나눠도 임포트만 늘어난다. 2026-09-19에 **분할하지 않기로 결정**했다 — `twbmap.py`는 410줄이고, 줄 수는 분할 트리거로 쓰지 않는다. 나눌 이유가 생긴다면 "파싱만 따로 재사용한다" 같은 실제 필요이지 길이가 아니다.

예외는 `template.html` 하나다. HTML·JS 424줄을 파이썬 문자열 안에 넣으면 편집이 불가능해진다.

## 파이프라인

```
.twbx (zip)
   │  zipfile — 내부 .twb 하나만 꺼낸다 (.hyper는 열지 않는다)
   ▼
.twb (XML 수 MB)
   │  xml.etree.ElementTree
   ▼
{nodes, edges, analyses}          ← 단일 진실원. 모든 렌더러가 이것만 본다
   │                    ▲
   │                    └── descriptions.json (설명 병합)
   ├── json.dumps    → out/map.json
   ├── render_md     → out/map.md
   └── html_payload  → out/map.html  (template.html의 __DATA__ 치환)
```

의존성은 **stdlib 전부**: `zipfile`, `xml.etree.ElementTree`, `re`, `json`, `difflib`, `collections`, `argparse`, `unicodedata`.

CLI 규약은 같은 계열 비공개 도구의 CLI를 따른다 — `argparse`, `main(argv) -> int`, 종료코드 `0` 성공 / `1` 입력·환경 오류 / `2` 미해석 참조 있음(tabctl의 `2` = 게이트 거부와 같은 자리).

## 노드·엣지 모델

노드 5종:

| 종류 | 출처 |
|---|---|
| `source` | `calculation` 자식이 없는 `column` + `metadata-record/local-name` |
| `param` | `Parameters` 데이터소스의 `column` |
| `calc` | `column` 중 `calculation` 자식 보유 |
| `sheet` | `worksheets/worksheet/@name` |
| `dashboard` | `dashboards/dashboard/@name` |

기준 워크북의 종류별 수량은 `fixtures.local.json`에 있다(로컬 전용).

엣지 3종:

| 엣지 | 출처 |
|---|---|
| `calc → 참조 필드` | 수식을 정규식 `\[[^\]\[]+\]`로 훑어 참조를 뽑는다 |
| `sheet → 필드` | 시트의 `datasource-dependencies/column` |
| `dashboard → sheet` | 대시보드의 `zone/@name`이 시트명과 일치할 때 |

뷰어는 두 모드다. **리니지**는 고른 필드의 계보만 120노드까지 그리고, **전체 맵**은
`calc`·`param`·`source`를 한 번에 그린다(시트·대시보드는 뺀다 — 넣으면 노드와 엣지가 몇 배로
늘어 읽을 수 없다). 0층 노드가 많으면 한 열로 두었을 때 세로로 긴 리본이 되고 맞춤 배율이
0.1 아래로 떨어지므로, 층 안에서 30행마다 줄을 바꾼다(같은 층끼리는 엣지가 없어 선이
꼬이지 않는다).

필드를 고르면 어느 경로에서든(그래프 노드·좌측 목록·다른 탭의 필드명) 전체 맵이 풀리고 계보 화면이
된다. 모드 전환은 `setFull()` 한 곳에서만 하므로 버튼 표시와 실제 상태가 어긋나지 않는다.

**팬(드래그)은 3px 움직인 뒤에 `setPointerCapture`를 한다.** `pointerdown`에서 곧바로 잡으면
`click`이 `<svg>`로 리타깃돼 `.node`까지 내려오지 않아 노드 클릭이 통째로 죽는다. 사람 손은 누르고
떼는 사이 1~3px 움직이므로 항상 그렇게 되고, 0px 합성 클릭으로는 재현되지 않는다 —
실제로 한 번 그대로 나갔다. `test_pointerdown_does_not_capture`가 막는다.

`<div id="name">`은 쓰지 않는다. 브라우저 예약 전역 `window.name`(문자열)과 충돌해
`name.innerHTML = ...`이 비-strict 모드에서 조용히 무시되고 탭이 빈 화면이 된다. `id="rename"`이다.

`layer`(층)는 상류가 없는 노드를 0으로 두고 위로 쌓아 계산한다. 기준 워크북에서 순환 0으로 확인됐다. 그래도 **순환 탐지는 남겨둔다** — 다른 워크북이 어떨지 모르고, 순환이 있으면 깊이 계산이 무한 재귀에 빠진다.

## 이름 해석 규칙

수식 안의 `[…]`를 실제 필드로 연결하는 순서다. **순서가 바뀌면 틀린다.**

1. `[DS].[field]` — 교차 데이터소스 참조를 **먼저** 잡는다. 이걸 나중에 처리하면 `[Parameters]`가 필드 이름으로 잘못 잡힌다
2. 같은 데이터소스의 `column/@name` 직결
3. 다른 데이터소스의 `column/@name` (같은 이름의 컬럼이 여러 데이터소스에 있을 수 있어 홈 데이터소스를 먼저 본다)
4. `metadata-record/local-name`
5. 그래도 안 풀리면 **`unresolved`에 넣고 리포트한다.** 지어내지 않는다

기준 워크북에서 이 순서로 **미해석 0건**이 된다.

한글 필드명 매칭에는 NFC 정규화 + casefold를 쓴다 (같은 계열 비공개 도구의 `fold()`와 같은 방식). 맥/윈도 간 자모 분해 차이로 같은 이름이 안 맞는 것을 막는다.

## 결정: LLM은 코드가 아니라 하네스 층에 둔다

**결정**: `twbmap.py`는 API를 호출하지 않는다. `descriptions.json`에 빈 슬롯만 만들고, Claude가 세션에서 수식·사용처를 읽어 채운다.

**이유**: CLI가 stdlib 0의존성·키 불필요 상태로 남는다. 그리고 사내 필드명 해석은 환각 위험이 실재하므로 `reviewed` 플래그라는 사람 검수 게이트가 필요한데, 코드 안에서 자동 생성하면 그 게이트가 없어진다. 같은 계열 비공개 도구의 설명 생성 스킬이 같은 구조다(초안 → 사람 검수).

**트레이드오프**: 필드 200개 남짓을 한 번에 자동 채우는 배치 실행이 안 된다. 세션에서 나눠 채워야 하고, fan-in이 높은 허브부터 우선순위를 둬야 한다.

```json
{ "[Calculation_000000000000000001]": {
    "caption": "계산식 A",
    "desc": "",
    "reviewed": false } }
```

`descriptions.json`은 실행할 때마다 자동 생성·병합되고 **커밋하지 않는다** — 사내 필드명이 그대로 들어간다.

재생성할 때 **기존 `desc`는 절대 덮어쓰지 않는다.** 없는 키만 추가한다. 이게 깨지면 사람이 쓴 설명이 조용히 날아간다.

## 함정 (실측으로 확인된 것)

- **`<calculation>` 태그 수는 실제 정의 수의 수십 배다.** 나머지는 시트마다 붙는 `<datasource-dependencies>` 사본이다. `root.iter('calculation')`으로 세면 통째로 부풀려진다. 정의는 `datasources/datasource/column`에서만 읽어라
- **`.twbx` 안의 `.hyper`는 수십 MB다.** 절대 읽지 마라. `zipfile`로 `.twb` 하나만 꺼낸다
- **파라미터는 `Parameters`라는 별도 데이터소스에 있다.** 일반 데이터소스만 훑으면 파라미터가 통째로 빠진다
- **대시보드 파라미터 컨트롤은 시트 의존성에 안 잡힌다.** 그래서 "미사용"이 아니라 "미사용 **후보**"다. 기준 워크북의 미사용 후보는 전부 파라미터였고, 실제로는 대시보드에서 쓰이고 있을 가능성이 높다
- **`(복사본)`은 내부 ID에만 있고 caption에는 없다.** caption으로 중복을 찾으면 0건이 나온다. 중복은 수식 정규화로 찾아야 한다
- **파라미터 수식은 상수다**(`2.`, `5.`, `FALSE`). 중복 탐지에서 제외하지 않으면 값이 같은 파라미터끼리 "동일 로직"으로 잡히는 오탐이 쏟아진다
- **`calculation` 자식이 없는 `<column>`도 원본 컬럼이다.** 계산식만 훑으면 metadata-record에도 없는 컬럼이 미해석으로 남는다. 이걸 놓쳐서 실제로 미해석이 남았다
- **내부명(`@name`)은 캡션과 다르고, 내용상 오도하기까지 한다.** 캡션이 `비율_A`인 필드의 내부명이 `[다른이름(복사본)_000000000000000002]`인 식이다 — 내부명을 읽고 의미를 판단하면 틀린다. 화면 표시는 **반드시 caption**으로 하라
- **대시보드 `zone`은 중복 등장한다.** 기준 워크북의 한 대시보드는 시트명 매치 수가 고유 시트 수의 두 배로 나왔다. 엣지는 반드시 집합으로 모아라
