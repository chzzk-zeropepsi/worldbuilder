"""Worldbuilder — local FastAPI app for novel worldbuilding.

Run:  cd server && uvicorn main:app --port 8765 --reload
UI:   http://localhost:8765
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import genre_kb
import llm

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Worldbuilder")

db.init_db()

# Cap how many related facts we hand the model per check — keeps the 7B context
# small enough to reason reliably.
MAX_RELATED_FACTS = 40


class EntryIn(BaseModel):
    type: str
    name: str
    aliases: list[str] = []
    fields: dict = {}
    body: str = ""
    links: list[int] = []


# ---------------------------------------------------------------------------
# Retrieval: which existing facts are relevant to this entry?
# ---------------------------------------------------------------------------
def _related_facts(entry, target_facts):
    """Pull facts from linked entries + entries whose name/alias is mentioned."""
    everything = db.all_facts_except(entry["id"])  # (rid, name, fact)
    if not everything:
        return []

    linked = set(entry.get("links", []))
    haystack = (entry.get("body", "") + " " + " ".join(target_facts)).lower()

    # Map entry_id -> set of its names/aliases for mention detection.
    entries = {e["id"]: e for e in db.list_entries()}

    scored = []
    for rid, name, fact in everything:
        score = 0
        if rid in linked:
            score += 10
        ent = entries.get(rid)
        if ent:
            for token in [ent["name"], *ent.get("aliases", [])]:
                if token and token.lower() in haystack:
                    score += 5
                    break
        if score:
            scored.append((score, rid, name, fact))

    if not scored:
        # No structural link — fall back to everything (capped) so a brand-new
        # bible still gets checked.
        return [(rid, name, fact) for rid, name, fact in everything][:MAX_RELATED_FACTS]

    scored.sort(key=lambda x: -x[0])
    return [(rid, name, fact) for _s, rid, name, fact in scored[:MAX_RELATED_FACTS]]


async def _reextract_and_check(entry_id):
    """Re-derive facts for an entry, then refresh its contradictions."""
    entry = db.get_entry(entry_id)
    facts = await llm.extract_facts(entry)
    db.replace_facts(entry_id, facts)

    db.clear_contradictions_for(entry_id)
    related = _related_facts(entry, facts)
    findings = await llm.check_contradictions(facts, related)
    for f in findings:
        db.add_contradiction(
            entry_id,
            f.get("src_entry"),
            f["fact_a"],
            f["fact_b"],
            f["severity"],
            f["explanation"],
        )
    return {"facts": facts, "findings": findings}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return await llm.ping()


@app.get("/api/types")
def types():
    return db.ENTRY_TYPES


# --- Projects (작품 관리) ----------------------------------------------------
@app.get("/api/projects")
def get_projects():
    return db.list_projects()


class ProjectIn(BaseModel):
    name: str


@app.post("/api/projects")
def make_project(body: ProjectIn):
    return {"id": db.create_project(body.name)}


@app.put("/api/projects/{pid}")
def edit_project(pid: int, body: ProjectIn):
    db.rename_project(pid, body.name)
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def remove_project(pid: int):
    db.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/activate")
def activate_project(pid: int):
    if not db.set_active_project(pid):
        raise HTTPException(404)
    return {"ok": True}


# --- Relations (관계도) ------------------------------------------------------
@app.get("/api/relation-types")
def relation_types():
    return db.RELATION_TYPES


@app.get("/api/relations")
def get_relations(kind: str = None):
    return db.list_relations(kind)


class RelationIn(BaseModel):
    from_id: int
    to_id: int
    kind: str
    type: str
    note: str = ""


@app.post("/api/relations")
def make_relation(body: RelationIn):
    return {"id": db.add_relation(body.from_id, body.to_id, body.kind, body.type, body.note)}


@app.delete("/api/relations/{rid}")
def remove_relation(rid: int):
    db.delete_relation(rid)
    return {"ok": True}


@app.post("/api/relations/analyze")
async def analyze_relations(kind: str = "character"):
    """LLM이 관계를 추론해 '제안'으로 반환(저장하지 않음). 사용자가 검토 후 추가."""
    if kind not in db.RELATION_TYPES:
        raise HTTPException(400)
    label = "인물" if kind == "character" else "세력"
    rtypes = db.RELATION_TYPES[kind]
    items = [e for e in db.list_entries() if e["type"] == kind]
    by_name = {e["name"]: e["id"] for e in items}
    found = await llm.analyze_relations(kind, label, rtypes, items)
    proposals = []
    for r in found:
        fid, tid = by_name.get(r["from"]), by_name.get(r["to"])
        if fid and tid and not db.relation_exists(fid, tid, r["type"]):
            proposals.append({
                "from_id": fid, "to_id": tid, "from_name": r["from"], "to_name": r["to"],
                "type": r["type"], "note": r["note"],
            })
    return {"proposals": proposals, "analyzed": len(items)}


# --- Story Studio (staged brainstorming) -----------------------------------
@app.get("/api/studio/meta")
def studio_meta():
    return {
        "genres": list(genre_kb.GENRE_KB.keys()),
        "stages": db.STUDIO_STAGES,
        "settings_questions": genre_kb.SETTINGS_QUESTIONS,
    }


@app.get("/api/genre-kb")
def get_genre_kb(genres: str = ""):
    """선택한 장르들의 지식베이스 + 추천 설정 병합."""
    picked = [g for g in genres.split(",") if g in genre_kb.GENRE_KB]
    kb = {g: genre_kb.GENRE_KB[g] for g in picked}
    return {"kb": kb, "suggested_settings": genre_kb.merge_settings(picked)}


@app.get("/api/story")
def get_story():
    return db.get_story()


class StoryIn(BaseModel):
    data: dict


@app.put("/api/story")
def put_story(body: StoryIn):
    db.save_story(body.data)
    return {"ok": True}


class SuggestIn(BaseModel):
    stage: str
    extra: str = ""


@app.post("/api/studio/suggest")
async def studio_suggest(body: SuggestIn):
    story = db.get_story()
    kb_text = genre_kb.kb_context(story.get("genres", []))
    return await llm.studio_suggest(body.stage, story, body.extra, kb_text)


@app.get("/api/entries")
def get_entries():
    return db.list_entries()


@app.get("/api/entries/{entry_id}")
def get_entry(entry_id: int):
    e = db.get_entry(entry_id)
    if not e:
        raise HTTPException(404)
    e["facts"] = db.get_facts(entry_id)
    return e


@app.post("/api/entries")
async def create_entry(entry: EntryIn):
    eid = db.create_entry(entry.model_dump())
    result = await _reextract_and_check(eid)
    return {"id": eid, **result}


@app.put("/api/entries/{entry_id}")
async def put_entry(entry_id: int, entry: EntryIn):
    if not db.get_entry(entry_id):
        raise HTTPException(404)
    db.update_entry(entry_id, entry.model_dump())
    result = await _reextract_and_check(entry_id)
    return {"id": entry_id, **result}


@app.delete("/api/entries/{entry_id}")
def del_entry(entry_id: int):
    db.delete_entry(entry_id)
    return {"ok": True}


@app.post("/api/entries/{entry_id}/expand")
async def expand(entry_id: int):
    entry = db.get_entry(entry_id)
    if not entry:
        raise HTTPException(404)
    names = [e["name"] for e in db.list_entries() if e["id"] != entry_id]
    return {"suggestions": await llm.expand_entry(entry, names)}


@app.get("/api/node-ops")
def node_ops():
    return [{"key": k, "label": v[0]} for k, v in llm.NODE_OPS.items()]


class NodeOpIn(BaseModel):
    op: str


@app.post("/api/entries/{entry_id}/brainstorm")
async def brainstorm(entry_id: int, body: NodeOpIn):
    entry = db.get_entry(entry_id)
    if not entry:
        raise HTTPException(404)
    story = db.get_story()
    kb_text = genre_kb.kb_context(story.get("genres", []))
    return {"suggestions": await llm.node_op(entry, body.op, story, kb_text)}


@app.post("/api/check-all")
async def check_all():
    """Re-run extraction + contradiction check across the whole bible."""
    total = 0
    for e in db.list_entries():
        result = await _reextract_and_check(e["id"])
        total += len(result["findings"])
    return {"contradictions": total}


@app.get("/api/contradictions")
def contradictions():
    return db.list_contradictions("open")


class StatusIn(BaseModel):
    status: str  # resolved | ignored | open


@app.post("/api/contradictions/{cid}/status")
def set_status(cid: int, body: StatusIn):
    db.set_contradiction_status(cid, body.status)
    return {"ok": True}


# Static UI -----------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
