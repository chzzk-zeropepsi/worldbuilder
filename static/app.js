"use strict";

const api = (path, opts) =>
  fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  }).then((r) => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  });

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

let TYPES = {};
let GENRES = [];
let STAGES = [];
let SETTINGS_Q = [];
let NODE_OPS = [];
let story = {}; // narrative scaffolding
let currentStage = "genre";

let entries = [];
let current = null;
let contradictions = [];

let projects = [];
let REL_TYPES = {};
let relKind = "character"; // 관계도 모드

// === boot ===================================================================
async function boot() {
  TYPES = await api("/types");
  const meta = await api("/studio/meta");
  GENRES = meta.genres;
  STAGES = meta.stages;
  SETTINGS_Q = meta.settings_questions || [];
  NODE_OPS = await api("/node-ops");
  REL_TYPES = await api("/relation-types");
  await loadProjects();
  story = await api("/story");
  story.settings = story.settings || {};

  // tabs
  document.querySelectorAll(".tab").forEach((t) => {
    t.onclick = () => switchView(t.dataset.view);
  });

  // bible editor wiring
  const sel = $("f-type");
  sel.innerHTML = Object.entries(TYPES).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
  sel.addEventListener("change", () => renderFields(current?.fields || {}));
  $("btn-new").onclick = newEntry;
  $("btn-check-all").onclick = checkAll;
  $("btn-delete").onclick = deleteCurrent;
  $("editor-form").addEventListener("submit", save);

  // timeline wiring
  $("btn-tl-suggest").onclick = suggestTimeline;
  $("btn-tl-add").onclick = () => { switchView("bible"); current = { type: "event", name: "", aliases: [], fields: {}, body: "", links: [] }; showForm(); };

  // project switcher
  $("project-select").onchange = (e) => switchProject(+e.target.value);
  $("btn-proj-new").onclick = newProject;
  $("btn-proj-rename").onclick = renameProject;
  $("btn-proj-del").onclick = deleteProject;

  // relations
  document.querySelectorAll(".rmode").forEach((b) => (b.onclick = () => {
    relKind = b.dataset.kind;
    document.querySelectorAll(".rmode").forEach((x) => x.classList.toggle("active", x === b));
    $("rel-proposals").innerHTML = "";
    renderRelations();
  }));
  $("btn-rel-analyze").onclick = analyzeRelations;
  $("btn-rel-add").onclick = addRelation;

  renderRail();
  renderStage();
  renderSummary();
  await refresh();
  await Promise.all([loadContradictions(), health()]);
}

function switchView(view) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  ["studio", "bible", "timeline", "relations"].forEach((v) =>
    $("view-" + v).classList.toggle("hidden", v !== view)
  );
  if (view === "bible") refresh();
  if (view === "timeline") renderTimeline();
  if (view === "relations") renderRelations();
}

async function health() {
  try {
    const h = await api("/health");
    const el = $("health");
    if (h.ok && h.model_present) { el.textContent = "● 연결됨"; el.className = "health ok"; }
    else { el.textContent = h.ok ? "● 모델 없음" : "● Ollama 꺼짐"; el.className = "health bad"; }
  } catch { $("health").className = "health bad"; }
}

const saveStory = () => api("/story", { method: "PUT", body: JSON.stringify({ data: story }) }).then(renderSummary);

// ============================================================================
//  STORY STUDIO
// ============================================================================
function renderRail() {
  $("stage-rail").innerHTML = STAGES.map(
    (s) => `<div class="stage-item ${s.key === currentStage ? "active" : ""}" data-key="${s.key}">
      <span class="dot ${stageDone(s.key) ? "done" : ""}"></span>${s.label}</div>`
  ).join("");
  $("stage-rail").querySelectorAll(".stage-item").forEach((el) => {
    el.onclick = () => { currentStage = el.dataset.key; renderRail(); renderStage(); };
  });
}

function stageDone(key) {
  if (key === "genre") return (story.genres || []).length > 0;
  if (key === "logline") return !!story.logline;
  if (key === "theme") return !!story.theme;
  if (key === "cliche") return (story.cliches || []).some((c) => c.decision);
  if (key === "character") return (story.committed_characters || 0) > 0;
  if (key === "world") return (story.committed_world || 0) > 0;
  if (key === "plot") return !!story.plot;
  return false;
}

function stageHeader(title, desc) {
  return `<div class="stage-head"><h2>${title}</h2><p>${desc}</p></div>`;
}
function suggestBtn(label) {
  return `<button id="btn-suggest" class="primary">💡 ${label}</button>`;
}
function spin() { $("stage-options").innerHTML = '<div class="spinner">생성 중… (로컬 모델, 수 초~수십 초)</div>'; }

function renderStage() {
  const p = $("stage-panel");
  const r = { genre: stageGenre, logline: stageLogline, theme: stageTheme,
              cliche: stageCliche, character: stageCharacter, world: stageWorld, plot: stagePlot }[currentStage];
  p.innerHTML = "";
  r(p);
}

// --- genre ---
function stageGenre(p) {
  p.innerHTML =
    stageHeader("장르 · 톤 · 설정", "장르를 고르면 통용 클리셰·기대요소가 자동 로드됩니다(기본값, 언제든 수정 가능). 톤과 프로젝트 설정을 정하세요.") +
    `<div class="chips" id="genre-chips">${GENRES.map(
      (g) => `<span class="chip ${(story.genres || []).includes(g) ? "on" : ""}" data-g="${g}">${g}</span>`
    ).join("")}</div>
    <div id="genre-kb"></div>
    <input id="tone-input" placeholder="톤 (예: 어둡고 비장한 / 가볍고 코믹한)" value="${esc(story.tone)}" />
    <div class="settings-q"><div class="sq-title">프로젝트 설정</div><div id="settings-fields"></div></div>
    ${suggestBtn("장르 변주 제안받기")}
    <div id="stage-options"></div>`;

  p.querySelectorAll("#genre-chips .chip").forEach((c) => {
    c.onclick = async () => {
      story.genres = story.genres || [];
      const g = c.dataset.g;
      story.genres.includes(g) ? (story.genres = story.genres.filter((x) => x !== g)) : story.genres.push(g);
      c.classList.toggle("on");
      await saveStory();
      loadGenreKb();
    };
  });
  $("tone-input").onchange = (e) => { story.tone = e.target.value.trim(); saveStory(); };
  renderSettingsFields();
  loadGenreKb();
  $("btn-suggest").onclick = async () => {
    if (!(story.genres || []).length) return alert("장르를 하나 이상 고르세요.");
    spin();
    const { options = [] } = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "genre" }) });
    renderOptionCards(options, (o) => { story.tone = o.title; $("tone-input").value = o.title; saveStory(); }, "이 방향 채택");
  };
}

function renderSettingsFields() {
  $("settings-fields").innerHTML = SETTINGS_Q.map((q) => {
    const v = story.settings[q.key];
    if (q.type === "bool")
      return `<label class="sq-row"><span>${q.label}</span>
        <select data-k="${q.key}">
          <option value="">미정</option>
          <option value="true" ${v === true ? "selected" : ""}>있음</option>
          <option value="false" ${v === false ? "selected" : ""}>없음</option>
        </select></label>`;
    return `<label class="sq-row"><span>${q.label}</span>
      <select data-k="${q.key}"><option value="">미정</option>
        ${q.options.map((o) => `<option ${v === o ? "selected" : ""}>${o}</option>`).join("")}
      </select></label>`;
  }).join("");
  $("settings-fields").querySelectorAll("select").forEach((s) => {
    s.onchange = () => {
      const val = s.value === "" ? undefined : s.value === "true" ? true : s.value === "false" ? false : s.value;
      if (val === undefined) delete story.settings[s.dataset.k];
      else story.settings[s.dataset.k] = val;
      saveStory();
    };
  });
}

async function loadGenreKb() {
  const box = $("genre-kb");
  if (!box) return;
  const gs = story.genres || [];
  if (!gs.length) { box.innerHTML = ""; return; }
  const { kb, suggested_settings } = await api("/genre-kb?genres=" + encodeURIComponent(gs.join(",")));
  box.innerHTML = Object.entries(kb).map(([g, d]) => `
    <div class="kb-card">
      <div class="kb-g">${g}</div>
      <div class="kb-row"><b>기본 클리셰</b> ${d.cliches.join(" · ")}</div>
      <div class="kb-row"><b>독자 기대</b> ${d.expectations.join(" · ")}</div>
      <div class="kb-row"><b>자주 쓰는 갈등</b> ${d.conflicts.join(" · ")}</div>
    </div>`).join("") +
    `<div class="kb-actions">
      <button id="kb-apply-settings">추천 설정값 적용</button>
      <button id="kb-seed-cliche">기본 클리셰를 점검 목록에 넣기</button>
    </div>`;
  $("kb-apply-settings").onclick = () => {
    Object.entries(suggested_settings).forEach(([k, v]) => { if (story.settings[k] === undefined) story.settings[k] = v; });
    saveStory(); renderSettingsFields();
  };
  $("kb-seed-cliche").onclick = () => {
    story.cliches = story.cliches || [];
    Object.values(kb).forEach((d) => d.cliches.forEach((cl) => {
      if (!story.cliches.find((c) => c.cliche === cl))
        story.cliches.push({ cliche: cl, why_common: "장르 기본 클리셰", decision: "", twist: "" });
    }));
    saveStory();
    alert("‘클리셰 점검’ 단계에 추가했습니다. 거기서 따름/비틂/버림을 정하세요.");
  };
}

// --- logline ---
function stageLogline(p) {
  p.innerHTML =
    stageHeader("전제 · 로그라인", "이야기의 한 줄 줄기입니다. 제안받아 고르거나 직접 다듬으세요.") +
    `<textarea id="logline-text" rows="3" placeholder="로그라인 한 줄…">${esc(story.logline)}</textarea>
    ${suggestBtn("로그라인 4개 제안받기")}<div id="stage-options"></div>`;
  $("logline-text").onchange = (e) => { story.logline = e.target.value.trim(); saveStory(); };
  $("btn-suggest").onclick = async () => {
    spin();
    const { options = [] } = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "logline" }) });
    renderOptionCards(options, (o) => { story.logline = o.title; $("logline-text").value = o.title; saveStory(); }, "이 로그라인 채택");
  };
}

// --- theme ---
function stageTheme(p) {
  p.innerHTML =
    stageHeader("테마 · 메시지", "이야기가 던질 핵심 질문입니다.") +
    `<textarea id="theme-text" rows="2" placeholder="테마…">${esc(story.theme)}</textarea>
    ${suggestBtn("테마 제안받기")}<div id="stage-options"></div>`;
  $("theme-text").onchange = (e) => { story.theme = e.target.value.trim(); saveStory(); };
  $("btn-suggest").onclick = async () => {
    spin();
    const { options = [] } = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "theme" }) });
    renderOptionCards(options, (o) => { story.theme = o.title; $("theme-text").value = o.title; saveStory(); }, "이 테마 채택");
  };
}

// --- cliche ---
function stageCliche(p) {
  story.cliches = story.cliches || [];
  p.innerHTML =
    stageHeader("클리셰 점검", "장르 클리셰를 가져와 각각 [따름 / 비틂 / 버림]을 정하세요. ‘비틂’은 비트는 방법까지 제안받습니다.") +
    suggestBtn("장르 클리셰 가져오기") + `<div id="cliche-list"></div><div id="stage-options"></div>`;
  $("btn-suggest").onclick = async () => {
    $("cliche-list").innerHTML = '<div class="spinner">클리셰 분석 중…</div>';
    const { items = [] } = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "cliche" }) });
    // merge with any existing decisions
    items.forEach((it) => {
      if (!story.cliches.find((c) => c.cliche === it.cliche))
        story.cliches.push({ cliche: it.cliche, why_common: it.why_common, decision: "", twist: "" });
    });
    saveStory();
    renderClicheList();
  };
  renderClicheList();
}

function renderClicheList() {
  const wrap = $("cliche-list");
  if (!wrap) return;
  if (!(story.cliches || []).length) { wrap.innerHTML = '<div class="empty">아직 없습니다. 위 버튼을 누르세요.</div>'; return; }
  wrap.innerHTML = story.cliches.map((c, i) => `
    <div class="cliche">
      <div class="cl-text">${esc(c.cliche)}</div>
      <div class="cl-why">${esc(c.why_common)}</div>
      <div class="cl-acts">
        ${["따름", "비틂", "버림"].map((d) => `<button class="${c.decision === d ? "on" : ""}" data-i="${i}" data-d="${d}">${d}</button>`).join("")}
      </div>
      ${c.decision === "비틂" ? `<div class="cl-twist">${c.twist ? "↳ " + esc(c.twist) : '<button class="twist-btn" data-i="' + i + '">비트는 방법 제안받기</button>'}</div>` : ""}
    </div>`).join("");

  wrap.querySelectorAll(".cl-acts button").forEach((b) => {
    b.onclick = () => { story.cliches[+b.dataset.i].decision = b.dataset.d;
      if (b.dataset.d !== "비틂") story.cliches[+b.dataset.i].twist = "";
      saveStory(); renderClicheList(); renderRail(); };
  });
  wrap.querySelectorAll(".twist-btn").forEach((b) => {
    b.onclick = async () => {
      const i = +b.dataset.i;
      b.textContent = "생성 중…";
      const { options = [] } = await api("/studio/suggest", {
        method: "POST", body: JSON.stringify({ stage: "twist", extra: "비틀 클리셰: " + story.cliches[i].cliche }) });
      renderOptionCards(options, (o) => { story.cliches[i].twist = o.title; saveStory(); renderClicheList(); }, "이 비틀기 채택");
    };
  });
}

// --- character ---
function stageCharacter(p) {
  p.innerHTML =
    stageHeader("주요 인물", "지금까지 설정에 맞는 인물을 제안받아 ‘바이블에 추가’하면 인물 카드로 저장됩니다.") +
    suggestBtn("인물 4~5명 제안받기") + `<div id="stage-options"></div>`;
  $("btn-suggest").onclick = async () => {
    spin();
    const { characters = [] } = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "character" }) });
    $("stage-options").innerHTML = characters.map((c, i) => `
      <div class="opt-card" data-i="${i}">
        <div class="ch-row"><input class="ce-name" value="${esc(c.name)}" placeholder="이름" /><input class="ce-role" value="${esc(c.role)}" placeholder="역할" /></div>
        <label class="ce-l">욕망</label><input class="ce-desire" value="${esc(c.desire)}" />
        <label class="ce-l">결함</label><input class="ce-flaw" value="${esc(c.flaw)}" />
        <label class="ce-l">비밀</label><input class="ce-secret" value="${esc(c.secret)}" />
        <label class="ce-l">기능/설명</label><textarea class="ce-note" rows="2">${esc(c.note)}</textarea>
        <div class="card-acts"><button class="add">＋ 바이블에 추가</button><button class="reject">거절</button></div>
      </div>`).join("") || '<div class="empty">제안이 없습니다.</div>';
    $("stage-options").querySelectorAll(".opt-card").forEach((card) => {
      const g = (cls) => card.querySelector(cls).value.trim();
      card.querySelector(".add").onclick = async (e) => {
        await api("/entries", { method: "POST", body: JSON.stringify({
          type: "character", name: g(".ce-name") || "이름 없음", aliases: [],
          fields: { 역할: g(".ce-role"), 목적: g(".ce-desire"), 비밀: g(".ce-secret") },
          body: `${g(".ce-note")}\n결함: ${g(".ce-flaw")}`, links: [],
        }) });
        story.committed_characters = (story.committed_characters || 0) + 1;
        saveStory(); renderRail();
        e.target.textContent = "✓ 추가됨"; e.target.disabled = true;
      };
      card.querySelector(".reject").onclick = () => card.remove();
    });
  };
}

// --- world ---
function stageWorld(p) {
  p.innerHTML =
    stageHeader("세계 핵심 설정", "이야기를 떠받칠 규칙들을 제안받아 바이블에 추가하세요. 각 규칙엔 대가/한계가 붙습니다.") +
    suggestBtn("핵심 설정 제안받기") + `<div id="stage-options"></div>`;
  $("btn-suggest").onclick = async () => {
    spin();
    const { options = [] } = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "world" }) });
    $("stage-options").innerHTML = options.map((o, i) => `
      <div class="opt-card" data-i="${i}">
        <input class="we-title" value="${esc(o.title)}" placeholder="이름" />
        <textarea class="we-detail" rows="3">${esc(o.detail)}</textarea>
        <div class="card-acts"><span class="role">${esc(TYPES[o.type]?.label || o.type)}</span>
          <button class="add">＋ 바이블에 추가</button><button class="reject">거절</button></div>
      </div>`).join("") || '<div class="empty">제안이 없습니다.</div>';
    $("stage-options").querySelectorAll(".opt-card").forEach((card) => {
      const o = options[+card.dataset.i];
      card.querySelector(".add").onclick = async (e) => {
        await api("/entries", { method: "POST", body: JSON.stringify({
          type: TYPES[o.type] ? o.type : "concept", name: card.querySelector(".we-title").value.trim() || "이름 없음",
          aliases: [], fields: {}, body: card.querySelector(".we-detail").value, links: [] }) });
        story.committed_world = (story.committed_world || 0) + 1;
        saveStory(); renderRail();
        e.target.textContent = "✓ 추가됨"; e.target.disabled = true;
      };
      card.querySelector(".reject").onclick = () => card.remove();
    });
  };
}

// --- plot ---
function stagePlot(p) {
  p.innerHTML =
    stageHeader("플롯 골격", "지금까지의 모든 설정을 종합해 3막 골격을 짭니다.") +
    suggestBtn("플롯 골격 제안받기") + `<div id="stage-options"></div>`;
  if (story.plot) renderPlot(story.plot);
  $("btn-suggest").onclick = async () => {
    spin();
    const res = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "plot" }) });
    story.plot = res.acts || []; saveStory(); renderRail(); renderPlot(story.plot);
  };
}
function beatHtml(b) {
  // The model returns beats as either plain strings or {beat, description} objects.
  if (b && typeof b === "object")
    return `<li><b>${esc(b.beat || b.title || "")}</b>${b.description ? " — " + esc(b.description) : ""}</li>`;
  return `<li>${esc(b)}</li>`;
}
function renderPlot(acts) {
  $("stage-options").innerHTML = (acts || []).map((a) => `
    <div class="opt-card">
      <div class="opt-title">${esc(a.act)}</div>
      <ul class="beats">${(a.beats || []).map(beatHtml).join("")}</ul>
    </div>`).join("") || '<div class="empty">아직 없습니다.</div>';
}

// --- generic option cards (title + detail, pick action) ---
function renderOptionCards(options, onPick, pickLabel) {
  const box = $("stage-options");
  if (!options.length) { box.innerHTML = '<div class="empty">제안이 없습니다.</div>'; return; }
  box.innerHTML = options.map((o, i) => `
    <div class="opt-card" data-i="${i}">
      <input class="opt-edit" value="${esc(o.title)}" />
      <div class="opt-detail">${esc(o.detail)}</div>
      <div class="card-acts">
        <button class="pick">${pickLabel}</button>
        <button class="reject">거절</button>
      </div>
    </div>`).join("");
  box.querySelectorAll(".opt-card").forEach((card) => {
    const i = +card.dataset.i;
    const pickBtn = card.querySelector(".pick");
    pickBtn.onclick = () => {
      onPick({ title: card.querySelector(".opt-edit").value.trim(), detail: options[i].detail });
      box.querySelectorAll(".pick").forEach((x) => { x.classList.remove("picked"); });
      pickBtn.classList.add("picked"); pickBtn.textContent = "✓ 채택됨";
    };
    card.querySelector(".reject").onclick = () => card.remove();
  });
}

// --- summary ---
function renderSummary() {
  const s = story;
  const rows = [];
  if ((s.genres || []).length) rows.push(["장르", s.genres.join(", ")]);
  if (s.tone) rows.push(["톤", s.tone]);
  if (s.logline) rows.push(["로그라인", s.logline]);
  if (s.theme) rows.push(["테마", s.theme]);
  const cl = (s.cliches || []).filter((c) => c.decision);
  if (cl.length) rows.push(["클리셰", cl.map((c) => `${c.cliche} → ${c.decision}${c.twist ? " (" + c.twist + ")" : ""}`).join("<br>")]);
  if (s.committed_characters) rows.push(["인물", s.committed_characters + "명 바이블에 추가됨"]);
  if (s.committed_world) rows.push(["설정", s.committed_world + "개 바이블에 추가됨"]);
  if (s.plot) rows.push(["플롯", (s.plot || []).map((a) => a.act).join(" → ")]);

  $("summary-body").className = rows.length ? "" : "empty";
  $("summary-body").innerHTML = rows.length
    ? rows.map(([k, v]) => `<div class="sum-row"><div class="sum-k">${k}</div><div class="sum-v">${v}</div></div>`).join("")
    : "단계를 진행하면 여기에 쌓입니다.";
}

// ============================================================================
//  BIBLE  (구조화 카드 + 모순 검사)
// ============================================================================
async function refresh() { entries = await api("/entries"); renderList(); }

function flaggedIds() {
  const s = new Set();
  contradictions.forEach((c) => { if (c.entry_a) s.add(c.entry_a); if (c.entry_b) s.add(c.entry_b); });
  return s;
}
function renderList() {
  if (!$("entry-list")) return;
  const flagged = flaggedIds();
  const groups = {};
  entries.forEach((e) => (groups[e.type] ??= []).push(e));
  $("entry-list").innerHTML = Object.entries(groups).map(([type, items]) => `
    <div class="type-group"><h3>${TYPES[type]?.label || type}</h3>
      ${items.map((e) => `<div class="entry-item ${current?.id === e.id ? "active" : ""} ${flagged.has(e.id) ? "flagged" : ""}" data-id="${e.id}">${esc(e.name)}</div>`).join("")}
    </div>`).join("") || '<div class="empty">아직 항목이 없습니다.</div>';
  $("entry-list").querySelectorAll(".entry-item").forEach((el) => (el.onclick = () => openEntry(+el.dataset.id)));
}

function newEntry() {
  current = { type: Object.keys(TYPES)[0], name: "", aliases: [], fields: {}, body: "", links: [] };
  showForm();
}
async function openEntry(id) { current = await api("/entries/" + id); showForm(); renderList(); }

function showForm() {
  $("editor-empty").classList.add("hidden");
  $("editor-form").classList.remove("hidden");
  $("f-type").value = current.type;
  $("f-name").value = current.name;
  $("f-aliases").value = (current.aliases || []).join(", ");
  $("f-body").value = current.body || "";
  renderFields(current.fields || {});
  renderLinks();
  $("save-status").textContent = "";
  $("btn-delete").style.display = current.id ? "" : "none";
  renderOpBar();
  $("suggest-list").innerHTML = current.id
    ? '<div class="empty">위 기능을 눌러 아이디어를 받아보세요.</div>'
    : '<div class="empty">먼저 저장하면 브레인스토밍을 쓸 수 있습니다.</div>';
}

function renderOpBar() {
  $("op-bar").innerHTML = NODE_OPS.map((o) => `<button class="op-btn" data-op="${o.key}" ${current.id ? "" : "disabled"}>${o.label}</button>`).join("");
  $("op-bar").querySelectorAll(".op-btn").forEach((b) => (b.onclick = () => doNodeOp(b.dataset.op)));
}

async function doNodeOp(op) {
  if (!current.id) return;
  $("suggest-list").innerHTML = '<div class="spinner">아이디어 생성 중…</div>';
  try {
    const { suggestions } = await api("/entries/" + current.id + "/brainstorm", { method: "POST", body: JSON.stringify({ op }) });
    renderSuggestions(suggestions);
  } catch (err) { $("suggest-list").innerHTML = '<div class="empty">오류: ' + err.message + "</div>"; }
}
function renderFields(values) {
  const fields = TYPES[$("f-type").value]?.fields || [];
  $("f-fields").innerHTML = fields.map((f) => `<div class="field-cell"><label>${f}</label><input data-field="${f}" value="${esc(values[f])}" /></div>`).join("");
}
function renderLinks() {
  const wrap = $("f-links");
  const links = new Set(current.links || []);
  wrap.innerHTML = entries.filter((e) => e.id !== current.id)
    .map((e) => `<span class="link-chip ${links.has(e.id) ? "on" : ""}" data-id="${e.id}">${esc(e.name)}</span>`).join("")
    || '<span class="empty" style="padding:0">다른 항목이 생기면 연결할 수 있습니다.</span>';
  wrap.querySelectorAll(".link-chip").forEach((chip) => (chip.onclick = () => chip.classList.toggle("on")));
}
function collectForm() {
  const fields = {};
  $("f-fields").querySelectorAll("input[data-field]").forEach((i) => (fields[i.dataset.field] = i.value.trim()));
  const links = [...$("f-links").querySelectorAll(".link-chip.on")].map((c) => +c.dataset.id);
  return {
    type: $("f-type").value, name: $("f-name").value.trim(),
    aliases: $("f-aliases").value.split(",").map((s) => s.trim()).filter(Boolean),
    fields, body: $("f-body").value, links,
  };
}
async function save(e) {
  e.preventDefault();
  const data = collectForm();
  if (!data.name) return ($("save-status").textContent = "이름을 입력하세요.");
  $("save-status").innerHTML = '<span class="spinner">저장 + 사실 추출 + 모순 검사 중…</span>';
  try {
    const res = current.id
      ? await api("/entries/" + current.id, { method: "PUT", body: JSON.stringify(data) })
      : await api("/entries", { method: "POST", body: JSON.stringify(data) });
    current = await api("/entries/" + res.id);
    await refresh(); await loadContradictions(); renderList();
    $("save-status").textContent = `저장됨 · 사실 ${res.facts.length}개 · 새 모순 ${res.findings.length}개`;
  } catch (err) { $("save-status").textContent = "오류: " + err.message; }
}
async function deleteCurrent() {
  if (!current.id || !confirm("이 항목을 삭제할까요?")) return;
  await api("/entries/" + current.id, { method: "DELETE" });
  current = null;
  $("editor-form").classList.add("hidden");
  $("editor-empty").classList.remove("hidden");
  await refresh(); await loadContradictions();
}
function renderSuggestions(list) {
  if (!list.length) return ($("suggest-list").innerHTML = '<div class="empty">제안이 없습니다.</div>');
  $("suggest-list").innerHTML = list.map((s, i) => `
    <div class="suggest" data-i="${i}">
      <div class="sfield">${esc(s.field)}</div>
      <textarea class="sug-edit" rows="3">${esc(s.value)}</textarea>
      <div class="card-acts">
        <button class="apply">적용</button>
        <button class="reject">거절</button>
      </div>
    </div>`).join("");
  $("suggest-list").querySelectorAll(".suggest").forEach((card) => {
    const field = list[+card.dataset.i].field;
    card.querySelector(".apply").onclick = () => {
      applySuggestion(field, card.querySelector(".sug-edit").value);
      card.remove();
    };
    card.querySelector(".reject").onclick = () => card.remove();
  });
}
function applySuggestion(field, value) {
  if (field === "body") $("f-body").value += ($("f-body").value ? "\n" : "") + value;
  else {
    const inp = $("f-fields").querySelector(`input[data-field="${field}"]`);
    if (inp) inp.value = value; else $("f-body").value += `\n${field}: ${value}`;
  }
  $("save-status").textContent = "제안 적용됨 — 저장하면 반영됩니다.";
}
async function loadContradictions() {
  contradictions = await api("/contradictions");
  $("contra-count").textContent = contradictions.length;
  renderContra(); renderList();
}
function renderContra() {
  if (!contradictions.length) return ($("contra-list").innerHTML = '<div class="empty">발견된 모순이 없습니다. ✅</div>');
  $("contra-list").innerHTML = contradictions.map((c) => `<div class="contra ${c.severity}">
    <div class="fa">▸ ${esc(c.name_a) || "?"}: ${esc(c.fact_a)}</div>
    <div class="fb">▸ ${esc(c.name_b) || "?"}: ${esc(c.fact_b)}</div>
    <div class="exp">${esc(c.explanation)}</div>
    <div class="acts"><button data-id="${c.id}" data-s="resolved">해결</button><button data-id="${c.id}" data-s="ignored">무시</button></div>
  </div>`).join("");
  $("contra-list").querySelectorAll("button").forEach((b) => (b.onclick = async () => {
    await api("/contradictions/" + b.dataset.id + "/status", { method: "POST", body: JSON.stringify({ status: b.dataset.s }) });
    await loadContradictions();
  }));
}
async function checkAll() {
  $("btn-check-all").textContent = "검사 중…"; $("btn-check-all").disabled = true;
  try { await api("/check-all", { method: "POST" }); await loadContradictions(); }
  finally { $("btn-check-all").textContent = "전체 모순 검사"; $("btn-check-all").disabled = false; }
}

// ============================================================================
//  TIMELINE  (event 엔트리를 시기순으로)
// ============================================================================
async function renderTimeline() {
  entries = await api("/entries");
  const events = entries.filter((e) => e.type === "event");
  events.sort((a, b) => String(a.fields?.시기 || "").localeCompare(String(b.fields?.시기 || ""), "ko"));
  const box = $("timeline-list");
  if (!events.length) { box.innerHTML = '<div class="empty">아직 사건이 없습니다. 위 버튼으로 추가하세요.</div>'; return; }
  box.innerHTML = events.map((e) => `
    <div class="tl-item" data-id="${e.id}">
      <div class="tl-when">${esc(e.fields?.시기) || "—"}</div>
      <div class="tl-dot"></div>
      <div class="tl-body">
        <div class="tl-name">${esc(e.name)}</div>
        <div class="tl-meta">${esc(e.fields?.장소) || ""}</div>
        <div class="tl-desc">${esc(e.body)}</div>
      </div>
    </div>`).join("");
  box.querySelectorAll(".tl-item").forEach((el) =>
    (el.onclick = () => { switchView("bible"); openEntry(+el.dataset.id); }));
}

async function suggestTimeline() {
  $("tl-options").innerHTML = '<div class="spinner">사건 생성 중…</div>';
  const { events = [] } = await api("/studio/suggest", { method: "POST", body: JSON.stringify({ stage: "timeline" }) });
  $("tl-options").innerHTML = events.map((ev, i) => `
    <div class="opt-card" data-i="${i}">
      <div class="ch-row"><input class="ee-name" value="${esc(ev.name)}" placeholder="사건명" /><input class="ee-when" value="${esc(ev.when)}" placeholder="시기" /></div>
      <label class="ce-l">장소</label><input class="ee-place" value="${esc(ev.place)}" />
      <label class="ce-l">원인</label><input class="ee-cause" value="${esc(ev.cause)}" />
      <label class="ce-l">결과</label><input class="ee-effect" value="${esc(ev.effect)}" />
      <label class="ce-l">메모</label><textarea class="ee-note" rows="2">${esc(ev.note)}</textarea>
      <div class="card-acts"><button class="add">＋ 연표에 추가</button><button class="reject">거절</button></div>
    </div>`).join("") || '<div class="empty">제안이 없습니다.</div>';
  $("tl-options").querySelectorAll(".opt-card").forEach((card) => {
    const g = (cls) => card.querySelector(cls).value.trim();
    card.querySelector(".add").onclick = async (e) => {
      await api("/entries", { method: "POST", body: JSON.stringify({
        type: "event", name: g(".ee-name") || "사건", aliases: [],
        fields: { 시기: g(".ee-when"), 장소: g(".ee-place"), 원인: g(".ee-cause"), 결과: g(".ee-effect") },
        body: g(".ee-note"), links: [] }) });
      e.target.textContent = "✓ 추가됨"; e.target.disabled = true;
      renderTimeline();
    };
    card.querySelector(".reject").onclick = () => card.remove();
  });
}

// ============================================================================
//  PROJECTS  (작품 관리)
// ============================================================================
async function loadProjects() {
  projects = await api("/projects");
  const sel = $("project-select");
  sel.innerHTML = projects.map((p) => `<option value="${p.id}" ${p.active ? "selected" : ""}>${esc(p.name)}</option>`).join("");
}

function activeProject() { return projects.find((p) => p.active); }

async function reloadActiveProject() {
  story = await api("/story");
  story.settings = story.settings || {};
  entries = await api("/entries");
  currentStage = "genre";
  current = null;
  renderRail(); renderStage(); renderSummary();
  $("editor-form").classList.add("hidden");
  $("editor-empty").classList.remove("hidden");
  await loadContradictions();
  const active = document.querySelector(".tab.active")?.dataset.view;
  if (active === "timeline") renderTimeline();
  if (active === "relations") renderRelations();
}

async function switchProject(pid) {
  await api(`/projects/${pid}/activate`, { method: "POST" });
  await loadProjects();
  await reloadActiveProject();
}

async function newProject() {
  const name = prompt("새 작품 이름:", "새 작품");
  if (!name) return;
  const { id } = await api("/projects", { method: "POST", body: JSON.stringify({ name }) });
  await loadProjects();
  $("project-select").value = id;
  await reloadActiveProject();
}

async function renameProject() {
  const p = activeProject();
  if (!p) return;
  const name = prompt("작품 이름 변경:", p.name);
  if (!name || name === p.name) return;
  await api(`/projects/${p.id}`, { method: "PUT", body: JSON.stringify({ name }) });
  await loadProjects();
}

async function deleteProject() {
  const p = activeProject();
  if (!p) return;
  if (projects.length <= 1) return alert("마지막 작품은 삭제할 수 없습니다.");
  if (!confirm(`작품 ‘${p.name}’과 그 안의 모든 설정·인물·관계를 삭제할까요? 되돌릴 수 없습니다.`)) return;
  await api(`/projects/${p.id}`, { method: "DELETE" });
  await loadProjects();
  await reloadActiveProject();
}

// ============================================================================
//  RELATIONS  (인물/세력 관계도)
// ============================================================================
const REL_COLOR = {
  우호: "#5ad15a", 동료: "#5ad15a", 동맹: "#5ad15a", 교역: "#4caf9a",
  적대: "#ff5c5c", 경쟁: "#ffb04c", 경쟁자: "#ffb04c",
  가족: "#c08bff", 연인: "#ff8bc0", 스승: "#6aa9ff", 제자: "#6aa9ff",
  주종: "#b0b6c0", 종속: "#b0b6c0", 중립: "#8b919c",
};
const relColor = (t) => REL_COLOR[t] || "#8b919c";

let relNodes = [], relRels = [];

async function renderRelations() {
  entries = await api("/entries");
  const nodes = entries.filter((e) => e.type === relKind);
  relNodes = nodes;
  relRels = await api("/relations?kind=" + relKind);

  // populate add-form selects
  const opts = nodes.map((n) => `<option value="${n.id}">${esc(n.name)}</option>`).join("");
  $("rel-from").innerHTML = opts;
  $("rel-to").innerHTML = opts;
  $("rel-type").innerHTML = (REL_TYPES[relKind] || []).map((t) => `<option>${t}</option>`).join("");

  drawGraph();
  renderRelList();
}

function drawGraph() {
  const svg = $("rel-svg");
  const wrap = $("rel-canvas-wrap");
  const W = wrap.clientWidth || 700, H = wrap.clientHeight || 600;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 80;
  const n = relNodes.length;
  if (!n) {
    svg.innerHTML = `<text x="${cx}" y="${cy}" fill="#8b919c" text-anchor="middle" font-size="14">${relKind === "character" ? "인물" : "세력"} 노드가 없습니다. 바이블에서 추가하세요.</text>`;
    return;
  }
  const pos = {};
  relNodes.forEach((nd, i) => {
    const a = (i / n) * 2 * Math.PI - Math.PI / 2;
    pos[nd.id] = n === 1 ? { x: cx, y: cy } : { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) };
  });

  let defs = `<defs>`;
  Object.entries(REL_COLOR).forEach(([k, c], i) => {
    defs += `<marker id="arw${i}" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="${c}"/></marker>`;
  });
  defs += `</defs>`;
  const arwId = (t) => "arw" + Object.keys(REL_COLOR).indexOf(t in REL_COLOR ? t : "");

  let edges = "", labels = "";
  relRels.forEach((r) => {
    const a = pos[r.from_id], b = pos[r.to_id];
    if (!a || !b) return;
    const c = relColor(r.type);
    // shorten to node edge
    const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
    const ux = dx / L, uy = dy / L, rad = 34;
    const x1 = a.x + ux * rad, y1 = a.y + uy * rad, x2 = b.x - ux * rad, y2 = b.y - uy * rad;
    const mid = REL_COLOR[r.type] ? arwId(r.type) : "arw0";
    edges += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" stroke-width="2" marker-end="url(#${mid})" opacity="0.85"/>`;
    labels += `<text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 4}" fill="${c}" font-size="11" text-anchor="middle">${esc(r.type)}</text>`;
  });

  let circles = "";
  relNodes.forEach((nd) => {
    const p = pos[nd.id];
    circles += `<g class="rel-node" data-id="${nd.id}" style="cursor:pointer">
      <circle cx="${p.x}" cy="${p.y}" r="30" fill="#23272f" stroke="#6aa9ff" stroke-width="2"/>
      <text x="${p.x}" y="${p.y + 4}" fill="#e6e8ec" font-size="12" text-anchor="middle">${esc(nd.name.slice(0, 6))}</text>
    </g>`;
  });

  svg.innerHTML = defs + edges + labels + circles;
  svg.querySelectorAll(".rel-node").forEach((g) => (g.onclick = () => { switchView("bible"); openEntry(+g.dataset.id); }));
}

function renderRelList() {
  const box = $("rel-list");
  if (!relRels.length) { box.innerHTML = '<div class="empty" style="padding:8px">아직 관계가 없습니다.</div>'; return; }
  box.innerHTML = relRels.map((r) => `
    <div class="rel-row">
      <span class="rel-dot" style="background:${relColor(r.type)}"></span>
      <span class="rel-txt">${esc(r.from_name)} <b style="color:${relColor(r.type)}">${esc(r.type)}</b> ${esc(r.to_name)}</span>
      <button data-id="${r.id}" class="rel-del">✕</button>
    </div>${r.note ? `<div class="rel-note">${esc(r.note)}</div>` : ""}`).join("");
  box.querySelectorAll(".rel-del").forEach((b) => (b.onclick = async () => {
    await api("/relations/" + b.dataset.id, { method: "DELETE" });
    renderRelations();
  }));
}

async function addRelation() {
  const from_id = +$("rel-from").value, to_id = +$("rel-to").value;
  const type = $("rel-type").value, note = $("rel-note").value.trim();
  if (!from_id || !to_id) return alert("노드를 선택하세요.");
  if (from_id === to_id) return alert("서로 다른 노드를 선택하세요.");
  await api("/relations", { method: "POST", body: JSON.stringify({ from_id, to_id, kind: relKind, type, note }) });
  $("rel-note").value = "";
  renderRelations();
}

async function analyzeRelations() {
  const btn = $("btn-rel-analyze");
  btn.textContent = "분석 중… (수십 초)"; btn.disabled = true;
  try {
    const { proposals = [], analyzed } = await api("/relations/analyze?kind=" + relKind, { method: "POST" });
    if (analyzed < 2) { alert("노드가 2개 이상 있어야 분석할 수 있습니다."); return; }
    renderProposals(proposals);
  } catch (e) { alert("오류: " + e.message); }
  finally { btn.textContent = "🤖 AI 관계 자동 분석"; btn.disabled = false; }
}

// AI가 제안한 관계를 '검토' 카드로 — 편집/추가/거절 후에야 저장된다.
function renderProposals(proposals) {
  const box = $("rel-proposals");
  if (!proposals.length) { box.innerHTML = '<div class="empty" style="padding:8px">새로 제안할 관계가 없습니다.</div>'; return; }
  const typeOpts = (sel) => (REL_TYPES[relKind] || []).map((t) => `<option ${t === sel ? "selected" : ""}>${t}</option>`).join("");
  box.innerHTML = `<div class="sq-title">AI 제안 (검토 후 추가)</div>` + proposals.map((p, i) => `
    <div class="prop-card" data-i="${i}">
      <div class="prop-line">${esc(p.from_name)} <select class="prop-type">${typeOpts(p.type)}</select> ${esc(p.to_name)}</div>
      <input class="prop-note" value="${esc(p.note)}" placeholder="근거/메모" />
      <div class="card-acts"><button class="add">＋ 추가</button><button class="reject">거절</button></div>
    </div>`).join("");
  box.querySelectorAll(".prop-card").forEach((card) => {
    const p = proposals[+card.dataset.i];
    card.querySelector(".add").onclick = async () => {
      await api("/relations", { method: "POST", body: JSON.stringify({
        from_id: p.from_id, to_id: p.to_id, kind: relKind,
        type: card.querySelector(".prop-type").value, note: card.querySelector(".prop-note").value.trim() }) });
      card.remove();
      await renderRelations();
    };
    card.querySelector(".reject").onclick = () => card.remove();
  });
}

boot();
