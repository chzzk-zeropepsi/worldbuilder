"""Ollama (EXAONE 3.5 7.8B) calls: fact extraction, contradiction check, brainstorm.

The model is small (7B, 8GB VRAM), so every prompt is kept narrow:
- extraction works on ONE entry at a time
- contradiction check is PAIRWISE over a small retrieved set, never the whole bible
"""
import json
import re

import httpx

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "exaone3.5:7.8b"
TIMEOUT = 120.0


async def _chat(system, user, force_json=True):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.4},
    }
    if force_json:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(OLLAMA_URL, json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]


def _loads(text, default):
    """Tolerant JSON parse — strip code fences / stray prose the model may add."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return default


# ---------------------------------------------------------------------------
# 1. Fact extraction (runs on save)
# ---------------------------------------------------------------------------
EXTRACT_SYS = (
    "너는 소설 세계관 설정집의 사실 추출기다. 주어진 설정 항목에서 "
    "검증 가능한 '원자적 사실' 문장만 뽑아낸다. 각 사실은 독립적으로 읽혀야 하고, "
    "주어를 생략하지 않으며, 한 문장에 하나의 단언만 담는다. 추측이나 미사여구는 버린다. "
    '반드시 {"facts": ["...", "..."]} 형식의 JSON만 출력한다.'
)


async def extract_facts(entry):
    fields_txt = "\n".join(
        f"- {k}: {v}" for k, v in entry.get("fields", {}).items() if v
    )
    user = (
        f"항목 유형: {entry['type']}\n"
        f"이름: {entry['name']}\n"
        f"별칭: {', '.join(entry.get('aliases', []))}\n"
        f"필드:\n{fields_txt}\n"
        f"서술:\n{entry.get('body', '')}\n\n"
        "위 항목에서 원자적 사실들을 추출하라."
    )
    out = _loads(await _chat(EXTRACT_SYS, user), {"facts": []})
    facts = out.get("facts", []) if isinstance(out, dict) else []
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]


# ---------------------------------------------------------------------------
# 2. Contradiction check (pairwise over a retrieved batch)
# ---------------------------------------------------------------------------
CHECK_SYS = (
    "너는 소설 세계관의 일관성 검사기다. '대상 항목'의 사실들과 '기존 설정' 사실들을 "
    "비교해 서로 모순되거나 충돌하는 쌍만 찾아낸다. 단순히 관련 없는 것은 무시한다. "
    "진짜 논리적·설정적 충돌만 보고한다. 각 모순에 대해 충돌하는 두 사실 문장, "
    "심각도(high/medium/low), 한국어 한 문장 설명을 제시한다. "
    '반드시 {"contradictions": [{"fact_a": "...", "fact_b": "...", '
    '"severity": "high|medium|low", "explanation": "..."}]} JSON만 출력한다. '
    "모순이 없으면 빈 배열을 반환한다."
)


async def check_contradictions(target_facts, related):
    """related: list of (entry_id, name, fact). Returns findings with src entry_id."""
    if not target_facts or not related:
        return []
    target_txt = "\n".join(f"- {f}" for f in target_facts)
    # Number related facts so the model can refer back; we map by exact text.
    related_txt = "\n".join(f"- [{rid}] {fact}" for rid, _name, fact in related)
    user = (
        f"대상 항목의 사실:\n{target_txt}\n\n"
        f"기존 설정의 사실 (앞의 [숫자]는 항목 id):\n{related_txt}\n\n"
        "대상과 기존 사이의 모순 쌍을 찾아라. fact_b에는 충돌한 기존 사실 문장을 그대로 적어라."
    )
    out = _loads(await _chat(CHECK_SYS, user), {"contradictions": []})
    findings = out.get("contradictions", []) if isinstance(out, dict) else []

    # Resolve fact_b back to its source entry_id by exact / fuzzy text match.
    by_text = {fact: rid for rid, _n, fact in related}
    results = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        fact_b = (f.get("fact_b") or "").strip()
        # The model often echoes the "[id] " prefix we numbered facts with; drop it.
        fact_b = re.sub(r"^\[\d+\]\s*", "", fact_b)
        src = by_text.get(fact_b)
        if src is None:
            for rid, _n, fact in related:
                if fact_b and (fact_b in fact or fact in fact_b):
                    src = rid
                    break
        results.append(
            {
                "fact_a": (f.get("fact_a") or "").strip(),
                "fact_b": fact_b,
                "severity": f.get("severity", "medium"),
                "explanation": (f.get("explanation") or "").strip(),
                "src_entry": src,
            }
        )
    return results


# ---------------------------------------------------------------------------
# 3. Brainstorm helpers (fill blanks / expand an entry)
# ---------------------------------------------------------------------------
EXPAND_SYS = (
    "너는 소설 세계관 브레인스토밍 파트너다. 주어진 항목의 빈 곳을 보고 "
    "기존 설정과 어울리는 구체적이고 신선한 제안을 한국어로 내놓는다. "
    "클리셰는 피하고, 서로 연결되는 디테일을 제안한다. "
    '반드시 {"suggestions": [{"field": "필드명 또는 body", "value": "제안 내용"}]} JSON만 출력한다.'
)


async def expand_entry(entry, context_names):
    fields_txt = "\n".join(
        f"- {k}: {v or '(빈칸)'}" for k, v in entry.get("fields", {}).items()
    )
    ctx = ", ".join(context_names) if context_names else "(없음)"
    user = (
        f"이미 존재하는 다른 설정들: {ctx}\n\n"
        f"항목 유형: {entry['type']}\n이름: {entry['name']}\n"
        f"필드:\n{fields_txt}\n서술:\n{entry.get('body', '')}\n\n"
        "빈칸을 채우거나 서술을 풍부하게 할 제안을 3~6개 내놓아라."
    )
    out = _loads(await _chat(EXPAND_SYS, user), {"suggestions": []})
    return out.get("suggestions", []) if isinstance(out, dict) else []


# ---------------------------------------------------------------------------
# 4. Story Studio — staged brainstorming from a blank page
# ---------------------------------------------------------------------------
def _settings_summary(settings):
    if not settings:
        return ""
    label = {"system": "시스템/상태창", "level": "레벨/등급", "magic": "마법/초능력",
             "scale": "세계규모", "nations": "국가수", "races": "종족"}
    parts = []
    for k, v in settings.items():
        if v is True:
            parts.append(label.get(k, k) + " 있음")
        elif v is False:
            parts.append(label.get(k, k) + " 없음")
        elif v:
            parts.append(f"{label.get(k, k)}: {v}")
    return ", ".join(parts)


def _story_summary(story):
    """Compact context string of what's decided so far, fed into every stage."""
    parts = []
    if story.get("genres"):
        parts.append("장르: " + ", ".join(story["genres"]))
    if story.get("tone"):
        parts.append("톤: " + story["tone"])
    s = _settings_summary(story.get("settings", {}))
    if s:
        parts.append("프로젝트 설정: " + s)
    if story.get("logline"):
        parts.append("로그라인: " + story["logline"])
    if story.get("theme"):
        parts.append("테마: " + story["theme"])
    decided = [
        f"{c['cliche']}→{c['decision']}" + (f"({c.get('twist','')})" if c.get("twist") else "")
        for c in story.get("cliches", [])
        if c.get("decision")
    ]
    if decided:
        parts.append("클리셰 결정: " + "; ".join(decided))
    return "\n".join(parts) if parts else "(아직 정해진 것 없음)"


# Per-stage (system_prompt, instruction) pairs. Each MUST emit JSON only.
_STAGE = {
    "genre": (
        "너는 소설 기획 파트너다. 사용자가 고른 기본 장르를 바탕으로, 흔하지 않은 "
        "장르 혼합·변주·톤 조합을 제안한다. 각 제안은 신선하되 실제로 쓸 수 있어야 한다. "
        '반드시 {"options":[{"title":"한 줄 컨셉","detail":"왜 흥미로운지 2문장"}]} JSON만 출력.',
        "위 장르를 비틀거나 다른 요소와 결합한 방향 4개를 제안하라.",
    ),
    "logline": (
        "너는 소설 기획 파트너다. 주어진 장르·톤에 맞는 '로그라인'(이야기 한 줄 줄기)을 제안한다. "
        "각 로그라인은 [주인공]+[목표]+[갈등/장애]를 담고 서로 확연히 달라야 한다. "
        '반드시 {"options":[{"title":"로그라인 한 줄","detail":"중심 갈등과 훅 2문장"}]} JSON만 출력.',
        "확연히 다른 방향의 로그라인 4개를 제안하라.",
    ),
    "theme": (
        "너는 소설 기획 파트너다. 주어진 로그라인이 던질 수 있는 핵심 테마/질문을 제안한다. "
        '반드시 {"options":[{"title":"테마 한 줄","detail":"이 테마가 이야기에서 어떻게 드러나는지"}]} JSON만 출력.',
        "이 이야기에 어울리는 테마 4개를 제안하라.",
    ),
    "cliche": (
        "너는 장르 분석가다. 주어진 장르에서 독자가 식상해하는 대표 클리셰들을 골라낸다. "
        '반드시 {"items":[{"cliche":"클리셰 한 줄","why_common":"왜 흔한지 한 문장"}]} JSON만 출력.',
        "이 장르의 대표 클리셰 6개를 나열하라. 사용자가 따를지/비틀지/버릴지 고를 것이다.",
    ),
    "twist": (
        "너는 소설 기획 파트너다. 주어진 클리셰를 신선하게 비트는 구체적 방법을 제안한다. "
        '반드시 {"options":[{"title":"비트는 방법 한 줄","detail":"어떻게 전복되는지 2문장"}]} JSON만 출력.',
        "이 클리셰를 비트는 서로 다른 방법 3개를 제안하라.",
    ),
    "character": (
        "너는 소설 기획 파트너다. 지금까지의 설정(장르·로그라인·테마·클리셰 결정)에 맞는 "
        "핵심 인물들을 제안한다. 각 인물은 뚜렷한 욕망과 치명적 결함을 가지며, 클리셰 결정과 "
        "충돌하지 않아야 한다. 역할은 주인공/적대자/조력자/관계인물 등으로 다양하게. "
        '반드시 {"characters":[{"name":"이름","role":"역할","desire":"욕망","flaw":"결함",'
        '"secret":"비밀","note":"이야기에서의 기능 한 줄"}]} JSON만 출력.',
        "서로 관계가 얽히는 핵심 인물 4~5명을 제안하라.",
    ),
    "world": (
        "너는 소설 기획 파트너다. 지금까지의 설정에 맞는 '세계의 핵심 규칙' 후보를 제안한다. "
        "마법/기술/사회/지리 등 이야기를 떠받칠 토대 규칙이며, 각 규칙엔 대가나 한계가 있어야 한다. "
        '반드시 {"options":[{"title":"규칙 한 줄","type":"magic|faction|geography|concept",'
        '"detail":"규칙과 그 대가/한계 2문장"}]} JSON만 출력.',
        "세계를 떠받칠 핵심 설정 4개를 제안하라.",
    ),
    "plot": (
        "너는 소설 기획 파트너다. 지금까지의 모든 설정을 종합해 3막 구조의 플롯 골격을 짠다. "
        "각 막은 핵심 비트 2~3개로. 앞서 정한 인물의 욕망/결함과 테마가 드러나야 한다. "
        '반드시 {"acts":[{"act":"1막 제목","beats":[{"beat":"비트 제목","description":"한 문장"}]}]} JSON만 출력.',
        "3막 구조의 플롯 골격을 제안하라.",
    ),
    "timeline": (
        "너는 소설 기획 파트너다. 지금까지의 설정에 맞는 세계의 '주요 역사 사건'들을 "
        "시간 순서대로 제안한다. 현재 이야기의 배경이 되는 과거 사건들을 중심으로. "
        '반드시 {"events":[{"name":"사건 이름","when":"시기(예: 제국력 412년)",'
        '"place":"장소","cause":"원인","effect":"결과","note":"이야기와의 연결 한 줄"}]} JSON만 출력.',
        "세계의 주요 역사 사건 5~6개를 시간 순서대로 제안하라.",
    ),
}


# Later stages must stay anchored to the chosen genre/logline — a small model
# otherwise drifts into an unrelated genre template (e.g. wuxia).
_ANCHOR = (
    " 반드시 위 '현재까지의 기획'의 장르·로그라인·테마에 충실하라. "
    "정해진 장르를 절대 다른 장르로 바꾸지 마라. 로그라인에 등장하는 설정·인물을 그대로 이어가라."
)
_ANCHORED = {"character", "world", "plot", "timeline"}


# Generation reference priority: user edits > project settings > genre clichés
# > general knowledge. Stated explicitly so the small model honors overrides.
_PRIORITY = (
    "\n\n[생성 규칙] 참조 우선순위를 반드시 지켜라: "
    "1) 사용자가 정한 설정/수정 내용 2) 프로젝트 설정 3) 장르 클리셰 4) 일반 지식. "
    "사용자 설정과 충돌하는 클리셰는 무시하라."
)


async def studio_suggest(stage, story, extra="", kb_text=""):
    spec = _STAGE.get(stage)
    if not spec:
        return {}
    system, instruction = spec
    user = f"현재까지의 기획:\n{_story_summary(story)}\n"
    if kb_text:
        user += f"\n선택 장르의 통용 지식(기본값, 사용자 설정이 우선):\n{kb_text}\n"
    if extra:
        user += f"\n추가 입력:\n{extra}\n"
    user += f"\n{instruction}"
    if stage in _ANCHORED:
        user += _ANCHOR
    user += _PRIORITY
    return _loads(await _chat(system, user), {})


# ---------------------------------------------------------------------------
# 5. Node brainstorm operations (작가가 노드별로 누르는 7기능)
# ---------------------------------------------------------------------------
# 작가의 기존 내용을 '대체'하지 않고, 적용 여부를 고를 수 있는 '제안'을 낸다.
NODE_OPS = {
    "expand":   ("확장", "이 설정/인물/플롯을 더 깊고 구체적으로 발전시켜라. 새 디테일을 더하라."),
    "twist":    ("반전", "예상 밖의 전개나 숨겨진 진실을 제안해 이 노드를 뒤집어라."),
    "darker":   ("어둡게", "더 비극적이고 어두운 방향으로 재해석하라."),
    "brighter": ("밝게", "더 희망적이고 따뜻한 방향으로 재해석하라."),
    "realistic":("현실적", "개연성과 인과를 강화해 더 그럴듯하게 다듬어라."),
    "trope":    ("클리셰 강화", "장르의 정석 클리셰를 살려 독자에게 익숙한 전개로 만들어라."),
    "subvert":  ("클리셰 파괴", "흔한 클리셰를 비틀어 독창적인 방향으로 만들어라."),
}

NODE_OP_SYS = (
    "너는 소설 설계 워크벤치의 아이디어 확장 엔진이다. 작가가 만든 노드를 대체하지 말고, "
    "요청한 방향의 '제안'을 내놓는다. 작가의 기존 설정은 존중하되 요청 방향으로 발전시킨다. "
    '반드시 {"suggestions":[{"field":"필드명 또는 body","value":"제안 내용"}]} JSON만 출력한다.'
)


async def node_op(entry, op, story=None, kb_text=""):
    spec = NODE_OPS.get(op)
    if not spec:
        return []
    _label, instruction = spec
    fields_txt = "\n".join(f"- {k}: {v}" for k, v in entry.get("fields", {}).items() if v)
    ctx = _story_summary(story) if story else ""
    user = (
        (f"프로젝트 맥락:\n{ctx}\n\n" if ctx else "")
        + (f"장르 통용 지식(기본값, 작가 설정 우선):\n{kb_text}\n\n" if kb_text else "")
        + f"노드 유형: {entry['type']}\n이름: {entry['name']}\n"
        + (f"필드:\n{fields_txt}\n" if fields_txt else "")
        + f"서술:\n{entry.get('body','')}\n\n"
        + f"요청 방향: [{spec[0]}] {instruction}\n"
        + "이 방향의 구체적 제안을 2~5개 내놓아라."
        + _PRIORITY
    )
    out = _loads(await _chat(NODE_OP_SYS, user), {"suggestions": []})
    return out.get("suggestions", []) if isinstance(out, dict) else []


# ---------------------------------------------------------------------------
# 6. Relationship analysis (인물/세력 관계도 자동 분석)
# ---------------------------------------------------------------------------
REL_SYS = (
    "너는 소설 설정 분석가다. 주어진 {kind_label} 목록과 각자의 설명을 읽고, 서로 간의 "
    "관계를 추론한다. 명시적으로 드러나거나 강하게 암시된 관계만 보고하고, 근거 없는 추측은 "
    "하지 않는다. 관계 유형은 다음 중에서만 고른다: {types}. "
    'from/to에는 목록에 있는 이름을 정확히 그대로 쓴다. '
    '반드시 {{"relations":[{{"from":"이름","to":"이름","type":"관계유형","note":"근거 한 줄"}}]}} JSON만 출력한다.'
)


async def analyze_relations(kind, kind_label, rtypes, items):
    """items: [{name, body, fields}]. Returns [{from,to,type,note}] (names)."""
    if len(items) < 2:
        return []
    listing = "\n".join(
        f"- {it['name']}: {it.get('body','')[:200]}"
        + (" / " + ", ".join(f"{k}:{v}" for k, v in (it.get('fields') or {}).items() if v) if it.get('fields') else "")
        for it in items
    )
    system = REL_SYS.format(kind_label=kind_label, types=", ".join(rtypes))
    user = f"{kind_label} 목록:\n{listing}\n\n이들 사이의 관계를 분석하라."
    out = _loads(await _chat(system, user), {"relations": []})
    rels = out.get("relations", []) if isinstance(out, dict) else []
    valid = {it["name"] for it in items}
    clean = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        f, t = (r.get("from") or "").strip(), (r.get("to") or "").strip()
        if f in valid and t in valid and f != t and r.get("type") in rtypes:
            clean.append({"from": f, "to": t, "type": r["type"], "note": (r.get("note") or "").strip()})
    return clean


async def ping():
    """Quick reachability check for Ollama + model."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "model_present": MODEL in names, "models": names}
    except Exception as e:
        return {"ok": False, "error": str(e)}
