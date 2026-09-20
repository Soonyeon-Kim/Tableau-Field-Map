#!/usr/bin/env python
"""Tableau 워크북(.twbx/.twb)에서 계산식 리니지 맵을 만든다.

    PYTHONUTF8=1 python twbmap.py <파일.twbx> --out out/

종료코드: 0 성공 / 1 입력·환경 오류 / 2 미해석 참조 있음
"""
from __future__ import annotations

import argparse
import collections
import difflib
import itertools
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SIMILAR_THRESHOLD = 0.88
FORMULA_MAX_LINES, FORMULA_MAX_CHARS = 4, 240  # 같은 계열 도구의 카탈로그 렌더러와 같은 절단 규칙
PARAM_DS = "Parameters"

REF_QUALIFIED = re.compile(r"\[([^\]\[]+)\]\.\[([^\]\[]+)\]")
REF_PLAIN = re.compile(r"\[[^\]\[]+\]")
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
STRING_LIT = re.compile(r"'[^']*'|\"[^\"]*\"")
PREFIX = re.compile(r"^([A-Za-z가-힣]+[_\-])")
DEFAULT_NAME = re.compile(r"^(계산|매개\s?변수|Calculation|Parameter)\s*\d*$")
LOD = re.compile(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", re.I)


def kids(root: ET.Element, tag: str):
    """root.find(tag) or [] 는 DeprecationWarning을 낸다. 없으면 빈 목록."""
    el = root.find(tag)
    return el if el is not None else []


def fold(s: str) -> str:
    """NFC 정규화 + casefold. 맥/윈도 자모 분해 차이를 흡수한다."""
    return unicodedata.normalize("NFC", s or "").casefold().strip()


def safe_parse(raw: bytes) -> ET.Element:
    """DTD가 있는 XML은 거부한다.

    stdlib ElementTree는 billion-laughs 류 엔티티 폭탄에 취약하다. 워크북은 남이 준
    파일일 수 있으므로 경계에서 막는다. Tableau가 쓴 .twb에는 DTD가 없으므로
    정상 파일은 걸리지 않는다. defusedxml을 쓰면 더 깔끔하지만 의존성이 늘어난다.
    """
    if re.search(rb"<!(DOCTYPE|ENTITY)", raw[:65536], re.I):
        raise SystemExit("[오류] DTD/엔티티 선언이 있는 워크북은 처리하지 않는다")
    return ET.fromstring(raw)


def load_twb(path: Path) -> ET.Element:
    """.twbx는 zip이다. 내부 .twb 하나만 꺼낸다 — .hyper는 열지 않는다(수십 MB)."""
    if path.suffix.lower() == ".twb":
        return safe_parse(path.read_bytes())
    with zipfile.ZipFile(path) as z:
        twb = [n for n in z.namelist() if n.lower().endswith(".twb")]
        if not twb:
            raise SystemExit(f"[오류] .twb가 들어있지 않다: {path}")
        return safe_parse(z.read(twb[0]))


def field_refs(formula: str):
    """수식에서 필드 참조를 뽑는다. (데이터소스|None, '[필드]') 목록.

    주석과 문자열 리터럴을 먼저 지운다. 리터럴 안의 대괄호를 필드로 오인하면 없는
    엣지가 생긴다. [DS].[field]를 먼저 잡아야 [Parameters]가 필드로 잘못 잡히지 않는다.
    """
    f = STRING_LIT.sub(" ", COMMENT.sub(" ", formula))
    out = [(m.group(1), f"[{m.group(2)}]") for m in REF_QUALIFIED.finditer(f)]
    out += [(None, m.group(0)) for m in REF_PLAIN.finditer(REF_QUALIFIED.sub(" ", f))]
    return out


def parse(root: ET.Element) -> dict:
    nodes: dict[str, dict] = {}
    by_ds: dict[str, dict[str, str]] = collections.defaultdict(dict)
    ds_alias: dict[str, str] = {}

    for ds in kids(root, "datasources"):
        dsname = ds.get("name")
        ds_alias[fold(dsname)] = dsname
        if ds.get("caption"):
            ds_alias[fold(ds.get("caption"))] = dsname
        # 정의는 datasource/column에만 있다. 시트의 datasource-dependencies는 사본이다.
        # calculation 자식이 없는 column도 원본 컬럼으로 반드시 담는다 —
        # 이걸 빼면 metadata-record에 없는 원본 컬럼이 미해석으로 남는다.
        for c in ds.findall("column"):
            calc = c.find("calculation")
            nid = f"{dsname}::{c.get('name')}"
            if calc is None:
                kind, formula = "source", ""
            else:
                is_param = dsname == PARAM_DS or c.get("param-domain-type") is not None
                kind, formula = ("param" if is_param else "calc"), (calc.get("formula") or "")
            nodes[nid] = dict(
                id=nid, kind=kind, ds=dsname, name=c.get("name"),
                caption=c.get("caption") or c.get("name").strip("[]"),
                formula=formula, datatype=c.get("datatype"), role=c.get("role"))
            by_ds[dsname][c.get("name")] = nid
        for m in ds.iter("metadata-record"):  # column으로 선언되지 않은 원본 컬럼
            local = m.findtext("local-name")
            if m.get("class") != "column" or not local or local in by_ds[dsname]:
                continue
            nid = f"{dsname}::{local}"
            nodes[nid] = dict(id=nid, kind="source", ds=dsname, name=local,
                              caption=local.strip("[]"), formula="",
                              datatype=m.findtext("local-type"), role=None)
            by_ds[dsname][local] = nid

    def resolve(ref_ds, ref_name, home_ds):
        if ref_ds:
            target_ds = ds_alias.get(fold(ref_ds))
            return by_ds.get(target_ds, {}).get(ref_name) if target_ds else None
        hit = by_ds.get(home_ds, {}).get(ref_name)
        if hit:
            return hit
        for idx in by_ds.values():  # 같은 이름이 여러 데이터소스에 있으면 홈 우선
            if ref_name in idx:
                return idx[ref_name]
        return None

    edges, unresolved = set(), []
    for n in list(nodes.values()):
        for ref_ds, ref_name in field_refs(n["formula"]):
            target = resolve(ref_ds, ref_name, n["ds"])
            if target is None:
                unresolved.append({"field": n["caption"], "ref": ref_name, "ds": ref_ds})
            elif target != n["id"]:
                edges.add((target, n["id"], "calc"))

    for w in kids(root, "worksheets"):
        sid = f"sheet::{w.get('name')}"
        nodes[sid] = dict(id=sid, kind="sheet", ds=None, name=w.get("name"),
                          caption=w.get("name"), formula="", datatype=None, role=None)
        for dep in w.iter("datasource-dependencies"):
            for c in dep.findall("column"):
                target = by_ds.get(dep.get("datasource"), {}).get(c.get("name"))
                if target:
                    edges.add((target, sid, "use"))

    sheet_names = {n["name"] for n in nodes.values() if n["kind"] == "sheet"}
    for d in kids(root, "dashboards"):
        did = f"dash::{d.get('name')}"
        nodes[did] = dict(id=did, kind="dashboard", ds=None, name=d.get("name"),
                          caption=d.get("name"), formula="", datatype=None, role=None)
        for z in d.iter("zone"):
            if z.get("name") in sheet_names:
                edges.add((f"sheet::{z.get('name')}", did, "show"))

    edge_list = sorted(edges)
    cycles = add_layers(nodes, edge_list)
    return {"nodes": nodes, "edges": edge_list, "unresolved": unresolved,
            "cycles": cycles, "by_ds": by_ds, "resolve": resolve}


def add_layers(nodes, edges) -> list:
    """상류가 없으면 0층. 순환이 있으면 -1로 표시하고 목록을 돌려준다."""
    up = collections.defaultdict(list)
    for a, b, _ in edges:
        up[b].append(a)
    memo, stack = {}, set()

    def depth(n):
        if n in memo:
            return memo[n]
        if n in stack:
            return -1
        stack.add(n)
        d = 0
        for p in up.get(n, ()):
            pd = depth(p)
            if pd < 0:
                memo[n] = -1
                stack.discard(n)
                return -1
            d = max(d, pd + 1)
        stack.discard(n)
        memo[n] = d
        return d

    for nid in nodes:
        nodes[nid]["layer"] = depth(nid)
    return [n for n, v in memo.items() if v < 0]


def canonical(model, nid: str) -> str:
    """필드 참조를 caption으로 치환하고 공백·대소문자를 정규화한다."""
    n = model["nodes"][nid]
    nodes, resolve = model["nodes"], model["resolve"]

    def to_caption(name, ds):
        t = resolve(ds, name, n["ds"])
        return "[" + (nodes[t]["caption"] if t else name.strip("[]")) + "]"

    f = COMMENT.sub(" ", n["formula"])
    f = REF_QUALIFIED.sub(lambda m: to_caption(f"[{m.group(2)}]", m.group(1)), f)
    f = REF_PLAIN.sub(lambda m: to_caption(m.group(0), None), f)
    return re.sub(r"\s+", " ", f).strip().upper()


def analyze(model) -> dict:
    nodes, edges = model["nodes"], model["edges"]
    down = collections.defaultdict(list)
    for a, b, _ in edges:
        down[a].append(b)

    calcs = [n for n in nodes.values() if n["kind"] == "calc"]
    canon = {n["id"]: canonical(model, n["id"]) for n in calcs}
    # 파라미터 수식은 상수(2., FALSE)라 빼지 않으면 무관한 필드가 "동일 로직"으로 잡힌다
    meaningful = {i: c for i, c in canon.items() if re.search(r"[\[A-Z]", c)}

    groups = collections.defaultdict(list)
    for i, c in meaningful.items():
        groups[c].append(i)
    identical = [{"formula": c, "fields": [nodes[i]["caption"] for i in v]}
                 for c, v in groups.items() if len(v) > 1]

    # ponytail: O(n²) 쌍 비교. 수백 개 규모면 즉시 끝난다.
    # 필드가 수천 개가 되면 길이 버킷으로 후보를 먼저 줄여라.
    forms = sorted(groups.items())
    similar = []
    for (ca, va), (cb, vb) in itertools.combinations(forms, 2):
        if abs(len(ca) - len(cb)) >= max(len(ca), len(cb)) * 0.3:
            continue
        ratio = difflib.SequenceMatcher(None, ca, cb).ratio()
        if ratio >= SIMILAR_THRESHOLD:
            similar.append({"ratio": round(ratio, 3), "a": nodes[va[0]]["caption"],
                            "b": nodes[vb[0]]["caption"]})
    similar.sort(key=lambda x: -x["ratio"])

    fan_in = {nid: len([d for d in down[nid] if nodes[d]["kind"] in ("calc", "param")])
              for nid in nodes}
    hubs = sorted((n for n in nodes.values() if fan_in[n["id"]] > 0),
                  key=lambda n: -fan_in[n["id"]])

    # 대시보드 파라미터 컨트롤은 시트 의존성에 안 잡힌다 → "미사용"이 아니라 "후보"
    unused = [n for n in nodes.values()
              if n["kind"] in ("calc", "param") and not down[n["id"]]]

    fields = [n for n in nodes.values() if n["kind"] in ("calc", "param")]
    families = collections.Counter(PREFIX.match(n["caption"]).group(1)
                                   for n in fields if PREFIX.match(n["caption"]))
    rename = [{"field": n["caption"], "why": "기본 이름이 그대로 남아 있다"}
              for n in fields if DEFAULT_NAME.match(n["caption"].strip())]
    rename += [{"field": n["caption"], "why": "이름에 (복사본)이 남아 있다"}
               for n in fields if "복사본" in n["caption"] or "copy" in fold(n["caption"])]

    complex_ = sorted(calcs, key=lambda n: -len(n["formula"]))
    return {
        "identical": identical,
        "similar": similar,
        "hubs": [{"field": n["caption"], "kind": n["kind"], "fan_in": fan_in[n["id"]]}
                 for n in hubs[:15]],
        "leaves": sum(1 for n in calcs if fan_in[n["id"]] == 0),
        "unused": [{"field": n["caption"], "kind": n["kind"]} for n in unused],
        "families": families.most_common(),
        "rename": rename,
        "complex": [{"field": n["caption"], "chars": len(n["formula"]), "layer": n["layer"],
                     "lod": bool(LOD.search(n["formula"]))} for n in complex_[:15]],
        "lod_count": sum(1 for n in calcs if LOD.search(n["formula"])),
        "max_layer": max((n["layer"] for n in nodes.values()
                          if n["kind"] in ("calc", "param", "source")), default=0),
    }


def sync_descriptions(path: Path, nodes) -> dict:
    """빈 슬롯만 추가한다. 기존 desc는 절대 덮어쓰지 않는다."""
    data = json.loads(path.read_text("utf-8")) if path.exists() else {}
    for n in nodes.values():
        if n["kind"] in ("calc", "param") and n["id"] not in data:
            data[n["id"]] = {"caption": n["caption"], "desc": "", "reviewed": False}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return data


def short(formula: str) -> str:
    lines = formula.splitlines()
    out = "\n".join(lines[:FORMULA_MAX_LINES])
    if len(out) > FORMULA_MAX_CHARS:
        out = out[:FORMULA_MAX_CHARS] + " …"
    elif len(lines) > FORMULA_MAX_LINES:
        out += "\n…"
    return out


def html_payload(data) -> str:
    """인라인 <script> 안에 넣을 JSON.

    필드 캡션이나 수식에 '</script>'가 들어 있으면 스크립트 태그를 탈출해 임의
    마크업이 실행된다. 워크북은 남이 준 파일일 수 있으므로 반드시 막는다.
    \\u 이스케이프는 JSON 문법상 동등하므로 값은 그대로 유지된다.
    """
    return (json.dumps(data, ensure_ascii=False, default=str)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def build(model, an, desc) -> dict:
    nodes = model["nodes"]
    return {
        "nodes": [{**n, "desc": desc.get(n["id"], {}).get("desc", ""),
                   "reviewed": desc.get(n["id"], {}).get("reviewed", False)}
                  for n in nodes.values()],
        "edges": [{"from": a, "to": b, "kind": k} for a, b, k in model["edges"]],
        "analyses": an,
        "unresolved": model["unresolved"],
        "cycles": model["cycles"],
        "counts": collections.Counter(n["kind"] for n in nodes.values()),
    }


def render_md(data) -> str:
    c, an = data["counts"], data["analyses"]
    L = ["# 계산식 리니지 맵", "",
         f"- 계산식 {c['calc']} · 파라미터 {c['param']} · 원본컬럼 {c['source']}"
         f" · 시트 {c['sheet']} · 대시보드 {c['dashboard']}",
         f"- 최대 리니지 층 {an['max_layer']} · 순환 {len(data['cycles'])}"
         f" · 해석 실패 참조 {len(data['unresolved'])}",
         f"- LOD 계산식 {an['lod_count']}개", ""]

    L += ["## 통합 후보 (근거: 강함)", ""]
    if an["identical"]:
        L += ["### 완전 동일 로직", ""]
        L += [f"- `{', '.join(g['fields'])}` — `{short(g['formula'])}`" for g in an["identical"]]
        L += [""]
    L += [f"### 유사 로직 ({SIMILAR_THRESHOLD} 이상, {len(an['similar'])}쌍)", "",
          "| 유사도 | 필드 A | 필드 B |", "|---|---|---|"]
    L += [f"| {s['ratio']} | {s['a']} | {s['b']} |" for s in an["similar"][:40]]
    if len(an["similar"]) > 40:
        L += ["", f"… 외 {len(an['similar']) - 40}쌍은 `map.json`에 있다."]
    L += [""]

    L += ["## 재사용도", "", "| 필드 | 종류 | 참조하는 수식 수 |", "|---|---|---|"]
    L += [f"| {h['field']} | {h['kind']} | {h['fan_in']} |" for h in an["hubs"]]
    L += ["", f"어떤 수식도 참조하지 않는 말단 계산식: **{an['leaves']}개**", ""]

    L += ["## 미사용 후보", "",
          "> ⚠️ 대시보드 파라미터 컨트롤로만 쓰이는 파라미터는 시트 의존성에 잡히지 않는다.",
          "> 지우기 전에 반드시 대시보드에서 직접 확인하라.", ""]
    L += [f"- {u['field']} ({u['kind']})" for u in an["unused"]] or ["없음"]
    L += [""]

    L += ["## 이름 점검 (근거: 약함)", "",
          "이미 존재하는 접두어 패밀리에서 이탈한 것만 지적한다. 전면 리네임 제안이 아니다.", "",
          "접두어 패밀리: " + ", ".join(f"`{p}`({n})" for p, n in an["families"][:10]), ""]
    L += [f"- {r['field']} — {r['why']}" for r in an["rename"]] or ["지적할 항목 없음"]
    L += [""]

    L += ["## 복잡도", "", "| 필드 | 수식 길이 | 층 | LOD |", "|---|---|---|---|"]
    L += [f"| {x['field']} | {x['chars']} | {x['layer']} | {'O' if x['lod'] else ''} |"
          for x in an["complex"]]

    if data["unresolved"]:
        L += ["", "## 해석 실패한 참조", "",
              "추측으로 메우지 않았다. 아래는 사람이 확인해야 한다.", ""]
        L += [f"- `{u['field']}` → `{u['ref']}`" for u in data["unresolved"]]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tableau 워크북 계산식 리니지 맵")
    ap.add_argument("workbook", help=".twbx 또는 .twb 경로")
    ap.add_argument("--out", default="out", help="출력 폴더 (기본: out)")
    ap.add_argument("--descriptions", default="descriptions.json")
    args = ap.parse_args(argv)

    wb = Path(args.workbook)
    if not wb.exists():
        print(f"[오류] 파일이 없다: {wb}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    model = parse(load_twb(wb))
    an = analyze(model)
    desc = sync_descriptions(Path(args.descriptions), model["nodes"])
    data = build(model, an, desc)

    (out / "map.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str), "utf-8")
    (out / "map.md").write_text(render_md(data), "utf-8")
    tpl = Path(__file__).with_name("template.html")
    if tpl.exists():
        payload = html_payload(data)
        (out / "map.html").write_text(
            tpl.read_text("utf-8").replace("__DATA__", payload), "utf-8")

    c = data["counts"]
    print(f"계산식 {c['calc']} · 파라미터 {c['param']} · 원본 {c['source']}"
          f" · 시트 {c['sheet']} · 대시 {c['dashboard']} | 최대 {an['max_layer']}층"
          f" | 유사 {len(an['similar'])}쌍 | 미해석 {len(data['unresolved'])}")
    print(f"→ {out}/map.json, map.md" + (", map.html" if tpl.exists() else ""))

    if data["unresolved"]:
        for u in data["unresolved"]:
            print(f"[미해석] {u['field']} → {u['ref']}", file=sys.stderr)
        print("[오류] 해석 못 한 참조는 추측으로 메우지 않는다 — 위 목록을 사람이 확인하라",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
