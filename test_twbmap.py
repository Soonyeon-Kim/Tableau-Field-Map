#!/usr/bin/env python
"""twbmap 자체 검사.

    PYTHONUTF8=1 python test_twbmap.py

기준 워크북의 실측값은 `fixtures.local.json`에 둔다(사내 필드명이 들어가므로 커밋하지
않는다). 워크북이나 픽스처 파일이 없으면 구조에 의존하지 않는 검사만 돌린다.
"""
import contextlib
import io
import json
import tempfile
from pathlib import Path

import twbmap

WB = next(Path(__file__).parent.glob("*.twbx"), None)
FIXTURES = Path(__file__).parent / "fixtures.local.json"


def test_field_refs():
    """문자열 리터럴과 주석 안의 대괄호를 필드로 오인하면 없는 엣지가 생긴다."""
    assert twbmap.field_refs("[a] + [b]") == [(None, "[a]"), (None, "[b]")]
    assert twbmap.field_refs("IF [x] = '[가짜]' THEN 1 END") == [(None, "[x]")]
    assert twbmap.field_refs("// [주석]\n[real]") == [(None, "[real]")]
    # [DS].[field]가 먼저 잡혀야 [Parameters]가 필드로 오인되지 않는다
    assert twbmap.field_refs("[Parameters].[P1] + [z]") == [("Parameters", "[P1]"), (None, "[z]")]


def test_cycle_detection():
    nodes = {"a": {}, "b": {}}
    cycles = twbmap.add_layers(nodes, [("a", "b", "calc"), ("b", "a", "calc")])
    assert set(cycles) == {"a", "b"}, cycles
    nodes = {"a": {}, "b": {}, "c": {}}
    assert twbmap.add_layers(nodes, [("a", "b", "calc"), ("b", "c", "calc")]) == []
    assert nodes["c"]["layer"] == 2


def test_dtd_rejected():
    try:
        twbmap.safe_parse(b"<!DOCTYPE x [<!ENTITY a 'b'>]><x/>")
    except SystemExit:
        return
    raise AssertionError("DTD가 있는 XML을 통과시켰다")


def test_html_payload_cannot_break_out():
    """필드 이름에 </script>가 있어도 스크립트 태그를 탈출하면 안 된다."""
    import json as _json
    evil = {"nodes": [{"caption": "</script><img src=x onerror=alert(1)>", "desc": "a & b"}]}
    out = twbmap.html_payload(evil)
    assert "</script" not in out.lower(), out
    assert "<" not in out and ">" not in out and "&" not in out, out
    assert _json.loads(out)["nodes"][0]["caption"] == evil["nodes"][0]["caption"]
    assert _json.loads(out)["nodes"][0]["desc"] == "a & b"


def test_descriptions_never_overwritten():
    """사람이 쓴 설명이 재생성으로 사라지면 안 된다."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "desc.json"
        nodes = {"x": {"id": "x", "kind": "calc", "caption": "필드X"}}
        twbmap.sync_descriptions(p, nodes)
        data = json.loads(p.read_text("utf-8"))
        data["x"]["desc"] = "사람이 쓴 설명"
        data["x"]["reviewed"] = True
        p.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        nodes["y"] = {"id": "y", "kind": "calc", "caption": "필드Y"}
        after = twbmap.sync_descriptions(p, nodes)
        assert after["x"]["desc"] == "사람이 쓴 설명"
        assert after["x"]["reviewed"] is True
        assert after["y"]["desc"] == ""


def test_pointerdown_does_not_capture():
    """pointerdown에서 곧바로 setPointerCapture를 하면 click이 <svg>로 리타깃돼
    .node까지 내려오지 않는다 — 노드 클릭이 통째로 죽는다.

    사람 손은 누르고 떼는 사이에 1~3px 움직이므로 실제로는 항상 죽고,
    0px 합성 클릭으로는 재현되지 않아 한 번 그대로 나갔다. 여기서 막는다.
    """
    tpl = (Path(__file__).parent / "template.html").read_text("utf-8")
    assert tpl.count("svg.addEventListener('pointerdown'") == 1, "핸들러가 바뀌었다 — 이 검사를 고쳐라"
    handler = tpl.split("svg.addEventListener('pointerdown'")[1].split("});")[0]
    assert "setPointerCapture" not in handler, "pointerdown에서 포인터를 잡으면 노드 클릭이 죽는다"
    assert "setPointerCapture" in tpl, "드래그가 화면 밖으로 나가면 끊긴다 — pointermove에서는 잡아야 한다"


def test_unresolved_is_not_silent():
    """해석 못 한 참조가 있으면 조용히 성공하면 안 된다 (PRD 성공 기준: 환각 없음)."""
    with tempfile.TemporaryDirectory() as d:
        wb = Path(d) / "x.twb"
        wb.write_text("<workbook><datasources><datasource name='DS'><column name='[a]'"
                      " caption='A'><calculation formula='[없는필드] + 1'/></column>"
                      "</datasource></datasources></workbook>", "utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = twbmap.main([str(wb), "--out", str(Path(d) / "out"),
                                "--descriptions", str(Path(d) / "desc.json")])
    assert code == 2, code
    assert "없는필드" in buf.getvalue(), buf.getvalue()


def test_workbook():
    """기준 워크북 실측값(fixtures.local.json). 파서를 고치면 이 숫자들이 먼저 깨진다."""
    fx = json.loads(FIXTURES.read_text("utf-8"))
    model = twbmap.parse(twbmap.load_twb(WB))
    an = twbmap.analyze(model)
    kinds = {}
    for n in model["nodes"].values():
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1

    for kind, want in fx["kinds"].items():
        assert kinds[kind] == want, (kind, kinds)

    # 추측으로 메우지 않는다 — 참조는 전부 실제 필드로 풀려야 한다
    assert model["unresolved"] == [], model["unresolved"]
    assert model["cycles"] == [], model["cycles"]
    assert an["max_layer"] == fx["max_layer"], an["max_layer"]
    assert len(an["similar"]) >= fx["min_similar"], len(an["similar"])

    # 접미 차이만 있는 쌍이 통합 후보에 실제로 올라오는가
    mark = fx["trend_marker"]
    trend = [s for s in an["similar"] if mark in s["a"] + s["b"]]
    assert len(trend) >= fx["min_trend_pairs"], trend

    # 대시보드 -> 시트. zone은 중복 등장하므로 엣지는 반드시 집합으로 모아야 한다.
    dash = [b for a, b, k in model["edges"] if k == "show" and b == fx["dashboard_id"]]
    assert len(dash) == fx["dashboard_sheets"], len(dash)

    # 리니지 1건 대조. 내부명(@name)은 캡션과 다르고 내용상 오도하기도 한다 —
    # 내부명을 신뢰하면 틀린다. 표시도 대조도 반드시 caption으로 한다.
    target = next(n for n in model["nodes"].values()
                  if n["caption"] == fx["lineage_target"])
    up = [model["nodes"][a]["caption"] for a, b, k in model["edges"] if b == target["id"]]
    assert sorted(up) == sorted(fx["lineage_upstream"]), up

    # 파라미터 상수 수식이 "동일 로직"으로 오탐되면 안 된다
    for g in an["identical"]:
        assert any(ch.isalpha() or ch == "[" for ch in g["formula"]), g


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    if WB is None or not FIXTURES.exists():
        tests = [t for t in tests if t.__name__ != "test_workbook"]
        print("! .twbx 또는 fixtures.local.json이 없어 워크북 검사는 건너뛴다")
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
