/* Hackathon Evaluation — single-viewport frontend */
(() => {
  const RUBRIC_KEYS = [
    ["problem_clarity",   "Problem Clarity"],
    ["agentic_complexity","Agentic Complexity"],
    ["live_functionality","Live Functionality"],
    ["business_impact",   "Business Impact"],
  ];
  const MAX_PER_CRIT = 25;

  const $ = (id) => document.getElementById(id);
  const panelLanding  = $("panel-landing");
  const panelProgress = $("panel-progress");
  const panelResults  = $("panel-results");
  const dropzone   = $("dropzone");
  const fileInput  = $("file-input");
  const fileLabel  = $("file-label");
  const fileMeta   = $("file-meta");
  const runBtn     = $("run-btn");
  const uploadBtn  = $("upload-btn");
  const appsList   = $("apps-list");
  const rightSub   = $("right-sub");
  const leaderboardTbody = $("leaderboard-tbody");
  const resultsMeta = $("results-meta");
  const backBtn    = $("back-btn");
  const drawer = $("drawer");
  const drawerContent = $("drawer-content");
  const drawerClose = $("drawer-close");
  const drawerBackdrop = $("drawer-backdrop");
  const exportBtn = $("export-btn");
  const exportCsvBtn = $("export-csv-btn");
  const deleteRunBtn = $("delete-run-btn");
  const navNew = $("nav-new");

  let selectedFile = null;
  let currentRun = null;  // { run_id, created_at, file_name, count, results }

  // ── Panel routing ──────────────────────────────────────────
  function showPanel(which) {
    panelLanding.classList.toggle("hidden",  which !== "landing");
    panelProgress.classList.toggle("hidden", which !== "progress");
    panelResults.classList.toggle("hidden",  which !== "results");
  }

  backBtn.addEventListener("click", () => {
    currentRun = null;
    selectedFile = null;
    fileInput.value = "";
    resetUpload();
    loadAppsLeaderboard();
    showPanel("landing");
  });
  navNew.addEventListener("click", (e) => { e.preventDefault(); backBtn.click(); });

  function resetUpload() {
    fileLabel.textContent = "Drop .xlsx or click to choose";
    fileMeta.textContent = "Team · Project · App ID · Pain · User · Impact";
    runBtn.disabled = true;
  }

  // ── File pick ──────────────────────────────────────────────
  dropzone.addEventListener("click", (e) => {
    if (e.target.closest(".btn")) return;
    fileInput.click();
  });
  uploadBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });
  fileInput.addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) handleFile(f);
  });
  ["dragenter","dragover"].forEach(ev => dropzone.addEventListener(ev, (e) => {
    e.preventDefault(); dropzone.classList.add("drag");
  }));
  ["dragleave","drop"].forEach(ev => dropzone.addEventListener(ev, (e) => {
    e.preventDefault(); dropzone.classList.remove("drag");
  }));
  dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  });

  function handleFile(f) {
    if (!f.name.toLowerCase().endsWith(".xlsx")) {
      alert("Please upload an .xlsx file");
      return;
    }
    selectedFile = f;
    fileLabel.textContent = f.name;
    fileMeta.textContent = `${(f.size/1024).toFixed(1)} KB · ready`;
    runBtn.disabled = false;
  }

  // ── Run evaluation ─────────────────────────────────────────
  runBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    runBtn.disabled = true;
    showPanel("progress");

    const fd = new FormData();
    fd.append("file", selectedFile);

    try {
      const r = await fetch("/api/evaluate", { method: "POST", body: fd });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`${r.status}: ${txt}`);
      }
      const data = await r.json();
      currentRun = data;
      renderResults(data);
      showPanel("results");
    } catch (err) {
      alert("Evaluation failed: " + err.message);
      showPanel("landing");
      runBtn.disabled = false;
    }
  });

  // ── Apps leaderboard (flattened across runs, sorted by final_score) ─
  async function loadAppsLeaderboard() {
    try {
      const r = await fetch("/api/apps-leaderboard?limit=100");
      const { apps } = await r.json();
      if (!apps.length) {
        appsList.innerHTML = `<div class="runs-empty">No runs yet.<br/>Upload a spreadsheet to get started.</div>`;
        rightSub.textContent = "Top apps across all runs";
        return;
      }
      rightSub.textContent = `${apps.length} app${apps.length===1?"":"s"} across all runs`;
      appsList.innerHTML = apps.map((a, i) => {
        const name = a.app_name || a.project_title || a.team_name || "—";
        const team = a.team_name ? (a.project_title && a.app_name ? `${a.team_name} · ${a.project_title}` : a.team_name) : (a.project_title || "");
        const isTop = i === 0;
        const noApp = !!a.fetch_error;
        return `
          <div class="app-item" data-run="${a.run_id}" data-app-id="${esc(a.app_id)}" title="Open run #${a.run_id}">
            <button class="app-del" data-run="${a.run_id}" title="Delete this run">×</button>
            <div class="app-rank ${isTop ? "top" : ""}">${i+1}</div>
            <div class="app-info">
              <div class="app-name">${esc(name)}</div>
              <div class="app-team">${esc(team)}${noApp ? ` · <span style="color:hsl(4,55%,65%)">no app</span>` : ""}</div>
            </div>
            <div class="app-score ${noApp ? "dim" : ""}">${(a.final_score || 0).toFixed(1)}</div>
          </div>`;
      }).join("");
      appsList.querySelectorAll(".app-item").forEach(el => {
        el.addEventListener("click", (e) => {
          if (e.target.closest(".app-del")) return;
          const id = parseInt(el.dataset.run);
          openRun(id);
        });
      });
      appsList.querySelectorAll(".app-del").forEach(btn => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const id = parseInt(btn.dataset.run);
          if (!confirm(`Delete run #${id}? This cannot be undone.`)) return;
          await deleteRun(id);
        });
      });
    } catch (err) {
      appsList.innerHTML = `<div class="runs-empty">Could not load leaderboard: ${esc(err.message)}</div>`;
    }
  }

  async function deleteRun(id) {
    try {
      const r = await fetch(`/api/runs/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(await r.text());
      if (currentRun && currentRun.run_id === id) {
        currentRun = null;
        showPanel("landing");
      }
      await loadAppsLeaderboard();
    } catch (err) {
      alert("Could not delete: " + err.message);
    }
  }

  deleteRunBtn.addEventListener("click", async () => {
    if (!currentRun || !currentRun.run_id) return;
    const id = currentRun.run_id;
    if (!confirm(`Delete run #${id}? This cannot be undone.`)) return;
    await deleteRun(id);
  });

  async function openRun(id) {
    showPanel("progress");
    try {
      const r = await fetch(`/api/runs/${id}`);
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      currentRun = data;
      renderResults(data);
      showPanel("results");
    } catch (err) {
      alert("Could not load run: " + err.message);
      showPanel("landing");
    }
  }

  function formatDate(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, {
        month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit"
      });
    } catch { return iso; }
  }

  // ── Results rendering ──────────────────────────────────────
  function renderResults(data) {
    const { results, run_id, created_at, file_name, count } = data;
    resultsMeta.textContent = `Run #${run_id || "—"} · ${count} apps${file_name ? " · " + file_name : ""}${created_at ? " · " + formatDate(created_at) : ""}`;

    leaderboardTbody.innerHTML = results.map((r, idx) => {
      const s = r.submission || {};
      const sc = r.scores || {};
      const isTop = r.rank === 1;
      const hasErr = !!r.fetch_error;
      const score = r.final_score ?? r.raw_total ?? 0;
      return `
        <tr class="${hasErr ? "error-row" : ""}">
          <td class="rank-cell ${isTop ? "top" : ""}">#${r.rank}</td>
          <td class="team-cell">
            <div class="team-name">${esc(s.team_name || "Unknown team")}${hasErr ? `<span class="error-badge">no app</span>` : ""}</div>
            <div class="team-project">${esc(s.project_title || "—")}</div>
          </td>
          <td class="score-cell sub">${pickScore(sc,"problem_clarity")}</td>
          <td class="score-cell sub">${pickScore(sc,"agentic_complexity")}</td>
          <td class="score-cell sub">${pickScore(sc,"live_functionality")}</td>
          <td class="score-cell sub">${pickScore(sc,"business_impact")}</td>
          <td class="final-cell ${isTop?"top":""}">${Number(score).toFixed(0)}</td>
          <td><button class="row-action" data-idx="${idx}">Details</button></td>
        </tr>
      `;
    }).join("");

    leaderboardTbody.querySelectorAll(".row-action").forEach(btn =>
      btn.addEventListener("click", () => openDrawer(results[parseInt(btn.dataset.idx)]))
    );
  }

  function pickScore(sc, key) {
    const entry = sc[key];
    if (!entry) return "—";
    return `${entry.score}`;
  }

  // ── Drawer ─────────────────────────────────────────────────
  drawerClose.addEventListener("click", closeDrawer);
  drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  function closeDrawer() { drawer.classList.add("hidden"); }

  function openDrawer(r) {
    drawer.classList.remove("hidden");
    const s = r.submission || {};
    const ctx = r.app_context;
    const sc = r.scores || {};

    const critHtml = RUBRIC_KEYS.map(([key, title]) => {
      const entry = sc[key] || { score: 0, justification: "" };
      const pct = Math.min(100, (entry.score / MAX_PER_CRIT) * 100);
      return `
        <div class="d-criterion">
          <div class="d-crit-head">
            <div class="d-crit-title">${title}</div>
            <div class="d-crit-score">${entry.score}<span style="font-size:13px;opacity:.4"> / ${MAX_PER_CRIT}</span></div>
          </div>
          <div class="d-crit-bar"><div class="d-crit-fill" style="width:${pct}%"></div></div>
          <div class="d-crit-just">${esc(entry.justification || "—")}</div>
        </div>`;
    }).join("");

    const bullets = (arr, klass="") => (arr || []).length
      ? `<ul class="d-bullets ${klass}">${arr.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`
      : `<div style="font-size:12.5px;color:var(--muted)">—</div>`;

    const ctxHtml = ctx ? `
      <div class="d-block">
        <div class="d-block-lbl">App</div>
        <div class="d-block-val"><strong>${esc(ctx.app_name || "—")}</strong> · status <code>${esc(ctx.status)}</code>${ctx.deployment_url ? ` · <a href="${esc(ctx.deployment_url)}" target="_blank" rel="noopener">live ↗</a>` : ""}</div>
      </div>
      <div class="d-block">
        <div class="d-block-lbl">Agents (${ctx.agent_count})</div>
        ${ctx.agents && ctx.agents.length ? `<div class="d-tag-row">${ctx.agents.map(a=>`<span class="d-tag">${esc(a.name || "agent")} · ${esc(a.model || "")}</span>`).join("")}</div>` : `<div style="color:var(--muted);font-size:12.5px">none</div>`}
      </div>
      <div class="d-block">
        <div class="d-block-lbl">Build signal</div>
        <div class="d-block-val">Commits ${ctx.commit_count} · Myra msgs ${ctx.myra_message_count} · Lyra msgs ${ctx.lyra_message_count}</div>
      </div>
      <details class="d-foldable"><summary>Input prompt</summary><pre>${esc(ctx.input_prompt || "—")}</pre></details>
      <details class="d-foldable"><summary>PRD excerpt</summary><pre>${esc(ctx.prd || "—")}</pre></details>
      <details class="d-foldable"><summary>Myra chat</summary><pre>${esc(ctx.myra_messages || "—")}</pre></details>
      <details class="d-foldable"><summary>Lyra build log</summary><pre>${esc(ctx.lyra_messages || "—")}</pre></details>
    ` : `
      <div class="d-block" style="border-color:rgba(205,90,90,.25);background:rgba(205,90,90,.04)">
        <div class="d-block-lbl" style="color:hsl(4,55%,45%)">App data</div>
        <div class="d-block-val">${esc(r.fetch_error || "Could not fetch from Architect.")}</div>
      </div>`;

    const drawerScore = r.final_score ?? r.raw_total ?? 0;
    drawerContent.innerHTML = `
      <div class="d-head">
        <div class="d-eyebrow">Rank #${r.rank} · score ${Number(drawerScore).toFixed(0)} / 100</div>
        <h2 class="d-title">${esc(s.team_name || "—")} <em>— ${esc(s.project_title || "")}</em></h2>
        <div class="d-project">${esc(s.elevator_pitch || "")}</div>
        <div class="d-scoreline">
          <div class="d-score-chip"><div class="d-score-lbl">Score</div><div class="d-score-val">${Number(drawerScore).toFixed(0)}</div></div>
          <div class="d-score-chip"><div class="d-score-lbl">Rank</div><div class="d-score-val">#${r.rank}</div></div>
          ${s.live_url ? `<div class="d-score-chip"><div class="d-score-lbl">Live</div><div class="d-score-val"><a href="${esc(s.live_url)}" target="_blank" rel="noopener" style="font-size:12px">open ↗</a></div></div>` : ""}
        </div>
      </div>
      <div class="d-section"><div class="d-section-title">Rubric breakdown</div>${critHtml}</div>
      <div class="d-section"><div class="d-section-title">Verdict</div>
        <div class="d-block"><div class="d-block-val">${esc(r.verdict || "—")}</div></div>
      </div>
      <div class="d-section"><div class="d-section-title">Strengths</div>${bullets(r.strengths)}</div>
      <div class="d-section"><div class="d-section-title">Weaknesses</div>${bullets(r.weaknesses)}</div>
      <div class="d-section"><div class="d-section-title">Red flags</div>${bullets(r.red_flags, "red")}</div>
      <div class="d-section"><div class="d-section-title">Submission fields</div>
        <div class="d-block"><div class="d-block-lbl">Pain point</div><div class="d-block-val">${esc(s.pain_point || "—")}</div></div>
        <div class="d-block"><div class="d-block-lbl">Primary user</div><div class="d-block-val">${esc(s.primary_user || "—")}</div></div>
        <div class="d-block"><div class="d-block-lbl">Impact claim</div><div class="d-block-val">${esc(s.impact || "—")}</div></div>
      </div>
      <div class="d-section"><div class="d-section-title">Fetched app</div>${ctxHtml}</div>
    `;
    drawerContent.parentElement.scrollTop = 0;
  }

  // ── Export ─────────────────────────────────────────────────
  exportBtn.addEventListener("click", () => {
    if (!currentRun) return;
    const blob = new Blob([JSON.stringify(currentRun, null, 2)], { type: "application/json" });
    download(blob, `hackathon-run-${currentRun.run_id || Date.now()}.json`);
  });
  exportCsvBtn.addEventListener("click", () => {
    if (!currentRun) return;
    const rows = [[
      "rank","team","project","app_id","score",
      "problem_clarity","agentic_complexity","live_functionality","business_impact",
      "verdict","live_url","fetch_error"
    ]];
    for (const r of currentRun.results) {
      const s = r.submission || {};
      const sc = r.scores || {};
      rows.push([
        r.rank, s.team_name, s.project_title, s.app_id,
        r.final_score ?? r.raw_total ?? 0,
        sc.problem_clarity?.score ?? "",
        sc.agentic_complexity?.score ?? "",
        sc.live_functionality?.score ?? "",
        sc.business_impact?.score ?? "",
        r.verdict || "", s.live_url || "", r.fetch_error || ""
      ]);
    }
    const csv = rows.map(row => row.map(csvEscape).join(",")).join("\n");
    download(new Blob([csv], { type: "text/csv" }), `hackathon-run-${currentRun.run_id || Date.now()}.csv`);
  });

  function csvEscape(v) {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g,'""')}"` : s;
  }
  function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 500);
  }
  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  }

  // ── Boot ───────────────────────────────────────────────────
  loadAppsLeaderboard();
})();
