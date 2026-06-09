"""SQLite persistence for the worldbuilder bible.

Everything is scoped to a *project* (a single novel/work). One project is the
"active" project at a time; entry/story/contradiction/relation queries operate on
it. Switching projects is just changing the active pointer in app_meta.
"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "worldbuilder.db"

# Entry types for the structured bible. Each maps to a set of typed fields the
# UI renders as form inputs (the LLM fills blanks / proposes values).
ENTRY_TYPES = {
    "geography": {"label": "지리/장소", "fields": ["기후", "지형", "주요_거점", "위험요소"]},
    "race": {"label": "종족", "fields": ["수명", "외형", "성향", "능력", "약점"]},
    "faction": {"label": "세력/국가", "fields": ["통치형태", "수도", "이념", "동맹", "적대"]},
    "magic": {"label": "마법/체계", "fields": ["동력원", "대가", "한계", "사용조건", "금기"]},
    "character": {"label": "인물", "fields": ["소속", "역할", "목적", "비밀", "관계"]},
    "religion": {"label": "종교/신화", "fields": ["주신", "교리", "성지", "금기", "세력"]},
    "event": {"label": "연표/사건", "fields": ["시기", "장소", "원인", "결과", "관련세력"]},
    "item": {"label": "물건/유물", "fields": ["기원", "능력", "대가", "현재위치", "소유자"]},
    "concept": {"label": "개념/기타", "fields": ["분류", "설명", "관련"]},
}

# Studio stages in order — drives the wizard rail in the UI.
STUDIO_STAGES = [
    {"key": "genre", "label": "장르·톤"},
    {"key": "logline", "label": "전제·로그라인"},
    {"key": "theme", "label": "테마·메시지"},
    {"key": "cliche", "label": "클리셰 점검"},
    {"key": "character", "label": "주요 인물"},
    {"key": "world", "label": "세계 핵심 설정"},
    {"key": "plot", "label": "플롯 골격"},
]

# Relationship types for the graph view, grouped by which node kind they connect.
RELATION_TYPES = {
    "character": ["우호", "적대", "가족", "연인", "스승", "제자", "경쟁자", "동료", "주종"],
    "faction": ["동맹", "적대", "종속", "경쟁", "교역", "중립"],
}


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _columns(c, table):
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL,
                data    TEXT NOT NULL DEFAULT '{}',
                created REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER,
                type        TEXT NOT NULL,
                name        TEXT NOT NULL,
                aliases     TEXT NOT NULL DEFAULT '[]',
                fields      TEXT NOT NULL DEFAULT '{}',
                body        TEXT NOT NULL DEFAULT '',
                links       TEXT NOT NULL DEFAULT '[]',
                created     REAL NOT NULL,
                updated     REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS facts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                text        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contradictions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_a     INTEGER REFERENCES entries(id) ON DELETE CASCADE,
                entry_b     INTEGER REFERENCES entries(id) ON DELETE CASCADE,
                fact_a      TEXT NOT NULL,
                fact_b      TEXT NOT NULL,
                severity    TEXT NOT NULL,
                explanation TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'open',
                created     REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS relations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER NOT NULL,
                from_id     INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                to_id       INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                kind        TEXT NOT NULL,      -- 'character' | 'faction'
                type        TEXT NOT NULL,      -- 우호/적대/동맹...
                note        TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_facts_entry ON facts(entry_id);
            CREATE INDEX IF NOT EXISTS idx_contra_status ON contradictions(status);
            CREATE INDEX IF NOT EXISTS idx_rel_project ON relations(project_id);
            """
        )

        # --- migrate older single-project DBs ------------------------------
        # (must precede the project_id index — an existing entries table from an
        #  older schema won't have been recreated by CREATE TABLE IF NOT EXISTS)
        if "project_id" not in _columns(c, "entries"):
            c.execute("ALTER TABLE entries ADD COLUMN project_id INTEGER")
        c.execute("CREATE INDEX IF NOT EXISTS idx_entries_project ON entries(project_id)")

        has_projects = c.execute("SELECT COUNT(*) n FROM projects").fetchone()["n"]
        if not has_projects:
            # Carry over the old single story_state blob, if any.
            old_data = "{}"
            if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='story_state'").fetchone():
                row = c.execute("SELECT data FROM story_state WHERE id=1").fetchone()
                if row:
                    old_data = row["data"]
            cur = c.execute(
                "INSERT INTO projects(name, data, created) VALUES(?,?,?)",
                ("프로젝트 1", old_data, time.time()),
            )
            pid = cur.lastrowid
            c.execute("UPDATE entries SET project_id=? WHERE project_id IS NULL", (pid,))
            _set_meta(c, "active_project", str(pid))

        # Ensure an active project is always set.
        if not _get_meta(c, "active_project"):
            first = c.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()
            if first:
                _set_meta(c, "active_project", str(first["id"]))


# --- app_meta helpers -------------------------------------------------------
def _get_meta(c, key):
    r = c.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def _set_meta(c, key, value):
    c.execute(
        "INSERT INTO app_meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def active_project_id():
    with _conn() as c:
        v = _get_meta(c, "active_project")
        return int(v) if v else None


# --- projects ---------------------------------------------------------------
def list_projects():
    with _conn() as c:
        active = _get_meta(c, "active_project")
        rows = c.execute("SELECT id, name, created FROM projects ORDER BY id").fetchall()
        return [
            {"id": r["id"], "name": r["name"], "created": r["created"],
             "active": str(r["id"]) == active}
            for r in rows
        ]


def create_project(name):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO projects(name, data, created) VALUES(?,?,?)",
            (name or "새 작품", "{}", time.time()),
        )
        pid = cur.lastrowid
        _set_meta(c, "active_project", str(pid))  # switch to the new one
        return pid


def rename_project(pid, name):
    with _conn() as c:
        c.execute("UPDATE projects SET name=? WHERE id=?", (name, pid))


def delete_project(pid):
    with _conn() as c:
        # cascade entries (and their facts/contradictions/relations) of this project
        c.execute("DELETE FROM relations WHERE project_id=?", (pid,))
        c.execute("DELETE FROM entries WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
        # repoint active project if we deleted it
        if _get_meta(c, "active_project") == str(pid):
            first = c.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()
            _set_meta(c, "active_project", str(first["id"]) if first else "")


def set_active_project(pid):
    with _conn() as c:
        if c.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
            _set_meta(c, "active_project", str(pid))
            return True
        return False


# --- story scaffolding (per active project) --------------------------------
def get_story():
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        if not pid:
            return {}
        r = c.execute("SELECT data FROM projects WHERE id=?", (pid,)).fetchone()
        return json.loads(r["data"]) if r else {}


def save_story(data):
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        if pid:
            c.execute("UPDATE projects SET data=? WHERE id=?",
                      (json.dumps(data, ensure_ascii=False), pid))


# --- entries (per active project) ------------------------------------------
def _row_to_entry(r):
    return {
        "id": r["id"],
        "type": r["type"],
        "name": r["name"],
        "aliases": json.loads(r["aliases"]),
        "fields": json.loads(r["fields"]),
        "body": r["body"],
        "links": json.loads(r["links"]),
        "created": r["created"],
        "updated": r["updated"],
    }


def list_entries():
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        rows = c.execute(
            "SELECT * FROM entries WHERE project_id=? ORDER BY type, name", (pid,)
        ).fetchall()
        return [_row_to_entry(r) for r in rows]


def get_entry(entry_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return _row_to_entry(r) if r else None


def create_entry(data):
    now = time.time()
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        cur = c.execute(
            "INSERT INTO entries(project_id,type,name,aliases,fields,body,links,created,updated)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                pid,
                data["type"],
                data["name"],
                json.dumps(data.get("aliases", []), ensure_ascii=False),
                json.dumps(data.get("fields", {}), ensure_ascii=False),
                data.get("body", ""),
                json.dumps(data.get("links", []), ensure_ascii=False),
                now,
                now,
            ),
        )
        return cur.lastrowid


def update_entry(entry_id, data):
    now = time.time()
    with _conn() as c:
        c.execute(
            "UPDATE entries SET type=?,name=?,aliases=?,fields=?,body=?,links=?,updated=?"
            " WHERE id=?",
            (
                data["type"],
                data["name"],
                json.dumps(data.get("aliases", []), ensure_ascii=False),
                json.dumps(data.get("fields", {}), ensure_ascii=False),
                data.get("body", ""),
                json.dumps(data.get("links", []), ensure_ascii=False),
                now,
                entry_id,
            ),
        )


def delete_entry(entry_id):
    with _conn() as c:
        c.execute("DELETE FROM entries WHERE id=?", (entry_id,))


def replace_facts(entry_id, facts):
    with _conn() as c:
        c.execute("DELETE FROM facts WHERE entry_id=?", (entry_id,))
        c.executemany(
            "INSERT INTO facts(entry_id,text) VALUES(?,?)",
            [(entry_id, f) for f in facts],
        )


def get_facts(entry_id):
    with _conn() as c:
        rows = c.execute("SELECT text FROM facts WHERE entry_id=?", (entry_id,)).fetchall()
        return [r["text"] for r in rows]


def all_facts_except(entry_id):
    """[(entry_id, name, fact)] for every fact in the SAME project, except entry_id."""
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        rows = c.execute(
            "SELECT f.entry_id, e.name, f.text FROM facts f"
            " JOIN entries e ON e.id=f.entry_id"
            " WHERE e.project_id=? AND f.entry_id<>?",
            (pid, entry_id),
        ).fetchall()
        return [(r["entry_id"], r["name"], r["text"]) for r in rows]


def clear_contradictions_for(entry_id):
    with _conn() as c:
        c.execute(
            "DELETE FROM contradictions WHERE entry_a=? OR entry_b=?",
            (entry_id, entry_id),
        )


def add_contradiction(entry_a, entry_b, fact_a, fact_b, severity, explanation):
    with _conn() as c:
        c.execute(
            "INSERT INTO contradictions(entry_a,entry_b,fact_a,fact_b,severity,explanation,created)"
            " VALUES(?,?,?,?,?,?,?)",
            (entry_a, entry_b, fact_a, fact_b, severity, explanation, time.time()),
        )


def list_contradictions(status="open"):
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        rows = c.execute(
            "SELECT c.*, ea.name AS name_a, eb.name AS name_b FROM contradictions c"
            " LEFT JOIN entries ea ON ea.id=c.entry_a"
            " LEFT JOIN entries eb ON eb.id=c.entry_b"
            " WHERE c.status=? AND ea.project_id=? ORDER BY c.created DESC",
            (status, pid),
        ).fetchall()
        return [dict(r) for r in rows]


def set_contradiction_status(cid, status):
    with _conn() as c:
        c.execute("UPDATE contradictions SET status=? WHERE id=?", (status, cid))


# --- relations (per active project) ----------------------------------------
def list_relations(kind=None):
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        q = ("SELECT r.*, a.name AS from_name, b.name AS to_name FROM relations r"
             " JOIN entries a ON a.id=r.from_id JOIN entries b ON b.id=r.to_id"
             " WHERE r.project_id=?")
        args = [pid]
        if kind:
            q += " AND r.kind=?"
            args.append(kind)
        return [dict(r) for r in c.execute(q, args).fetchall()]


def add_relation(from_id, to_id, kind, rtype, note=""):
    with _conn() as c:
        pid = _get_meta(c, "active_project")
        cur = c.execute(
            "INSERT INTO relations(project_id,from_id,to_id,kind,type,note)"
            " VALUES(?,?,?,?,?,?)",
            (pid, from_id, to_id, kind, rtype, note),
        )
        return cur.lastrowid


def delete_relation(rid):
    with _conn() as c:
        c.execute("DELETE FROM relations WHERE id=?", (rid,))


def relation_exists(from_id, to_id, rtype):
    with _conn() as c:
        return bool(c.execute(
            "SELECT 1 FROM relations WHERE from_id=? AND to_id=? AND type=?",
            (from_id, to_id, rtype),
        ).fetchone())
