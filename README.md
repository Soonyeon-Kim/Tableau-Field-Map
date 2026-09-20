# tableau_calculation_map

Tableau 워크북(`.twbx`)의 계산식이 **원본 컬럼에서 어떻게 만들어졌는지**를 그려주는 CLI.
의존 관계 목록이 아니라 리니지(계보) 파이프라인이고, 그 위에서 통합·리네임 후보까지 제안한다.

> Maps calculated-field lineage inside a Tableau workbook and reports consolidation
> candidates. Python stdlib only — no install, no API key, no network.

## 쓰는 법

```bash
PYTHONUTF8=1 python twbmap.py "<워크북>.twbx" --out out/
PYTHONUTF8=1 python test_twbmap.py       # 자체 검사
```

Python 3.9+ 외에 필요한 것이 없다. `pip install` 단계가 없다.
(Windows에서 `PYTHONUTF8=1`을 빼면 한글 출력에서 `UnicodeEncodeError`가 난다)

`out/`에 세 개가 만들어진다.

| 파일 | 용도 |
|---|---|
| `map.html` | 브라우저로 그냥 연다. 단일 파일·CDN 없음 → 오프라인·폐쇄망에서도 열린다 |
| `map.md` | 통합 후보·재사용도·미사용·이름 점검 리포트. git diff로 변경 추적 |
| `map.json` | 위 둘의 원자료 |

`map.html`은 리니지 그래프(정·역방향), 전체 맵, 미니맵, 통합 후보·이름 점검·복잡도 탭을 제공한다.
자세한 사용법은 [`ESSENTIAL.md`](ESSENTIAL.md).

## ⚠️ 산출물에는 워크북의 필드명이 그대로 들어간다

`out/`·`descriptions.json`·`*.local.*`은 `.gitignore`로 막혀 있다. **해제하지 마라.**
워크북 자체(`.twbx`/`.twb`/`.hyper`)도 마찬가지다 — 데이터가 파일 안에 내장된다.
이 저장소는 도구만 공개하고, 어떤 워크북에서도 나온 필드명·시트명을 담지 않는다.

## 설계

| 문서 | 내용 |
|---|---|
| [`ESSENTIAL.md`](ESSENTIAL.md) | 5분 요약 · 인수인계 |
| [`docs/PRD.md`](docs/PRD.md) | 무엇을·왜 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 어떻게 — 파이프라인, 이름 해석 규칙, **함정** |
| [`CLAUDE.md`](CLAUDE.md) | 코딩 에이전트용 작업 규칙 |

읽기 전용 도구다. 워크북을 다시 쓰지 않는다. 해석하지 못한 필드 참조는 추측으로 메우지 않고
목록을 출력한 뒤 종료코드 `2`로 실패한다.

## 라이선스

MIT — [`LICENSE`](LICENSE)
