/* Metamod:Source-Compiler (C++) – ab 1.2.0, Editor ab 1.3.0 */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const EXAMPLE = "https://github.com/Source2ZE/ServerListPlayersFix";
  let info = null;
  let file = null;
  let pollTimer = null;
  let lastResult = null;
  let mmReady = true;
  // Editor-Projekt: files = Map(pfad -> { text, bin, size })
  let P = null;

  // ---- Modus (C# / Metamod) ------------------------------------------------
  function setMode(mode, save) {
    const mm = mode === "metamod";
    $("cssharpMode").hidden = mm;
    $("metamodMode").hidden = !mm;
    document.querySelectorAll(".mode[data-mode]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === mode)));
    $("heroTitle").dataset.i18n = mm ? "hero.mm.title" : "hero.title";
    $("heroText").dataset.i18n = mm ? "hero.mm.text" : "hero.text";
    applyI18n();
    if (save) {
      store.set("cssc.mode", mode);
      try { history.replaceState(null, "", mm ? "#metamod" : location.pathname + location.search); } catch (e) { /* egal */ }
    }
  }

  // ---- Formular --------------------------------------------------------------
  const source = () => (document.querySelector('input[name="mmSource"]:checked') || {}).value || "git";
  const cfg = () => (document.querySelector('input[name="mmCfg"]:checked') || {}).value || "Release";

  function updateSource() {
    const git = source() === "git";
    $("mmGitBox").hidden = !git;
    $("mmZipBox").hidden = git;
  }

  function setFile(f) {
    if (!f) return;
    const limit = (info ? info.max_upload_mb : 20) * 1048576;
    if (!/\.zip$/i.test(f.name)) { toast(t("err.zip_invalid")); return; }
    if (f.size > limit) { toast(t("err.upload_too_big", { limit: limit / 1048576 })); return; }
    file = f;
    $("mmFileName").textContent = f.name + " · " + fmtSize(f.size);
    f.arrayBuffer().then((buf) => loadZip(buf, f.name.replace(/\.zip$/i, "").replace(/-(main|master)$/i, "")));
  }

  function fillRuntimes() {
    const sel = $("mmRuntime");
    const rts = (info && info.metamod_runtimes) || ["steamrt3"];
    const cur = sel.value || store.get("cssc.mmRuntime", rts[0]);
    sel.innerHTML = rts.map((r) => `<option value="${esc(r)}">${esc(t("mm.rt." + r))}</option>`).join("");
    sel.value = rts.includes(cur) ? cur : rts[0];
    $("mmRuntimeField").hidden = rts.length < 2;
  }

  function helpTexts() {
    const hosts = (info && info.git_hosts) || ["github.com"];
    $("mmGitHelp").textContent = t("mm.gitUrlHelp", { hosts: hosts.join(", ") });
    $("mmDropSub").textContent = t("settings.dropSub", { mb: info ? info.max_upload_mb : 20 });
  }

  // ---- Kompilieren -----------------------------------------------------------
  async function compile() {
    const fd = new FormData();
    if (P) {
      let blob;
      try { blob = await projectZip(); } catch (e) { toast(t("mm.zipLoadFailed")); return; }
      const limit = (info ? info.max_upload_mb : 20) * 1048576;
      if (blob.size > limit) { toast(t("mm.tooBig", { mb: limit / 1048576 })); return; }
      fd.append("file", blob, (P.name || "plugin") + ".zip");
    } else if (source() === "git") {
      const url = $("mmGitUrl").value.trim();
      if (!url) { toast(t("err.mm_no_source")); $("mmGitUrl").focus(); return; }
      fd.append("git_url", url);
      fd.append("git_ref", $("mmGitRef").value.trim());
    } else {
      if (!file) { toast(t("err.mm_no_source")); return; }
      fd.append("file", file, file.name);
    }
    fd.append("runtime", $("mmRuntime").value);
    fd.append("configuration", cfg());
    fd.append("tag", $("mmTag").value.trim());
    store.set("cssc.mmRuntime", $("mmRuntime").value);

    const btn = $("mmCompileBtn");
    btn.disabled = true;
    btn.textContent = t("settings.uploading");
    let r, d;
    try {
      r = await fetch(BASE + "/api/metamod/compile", { method: "POST", body: fd });
      d = await r.json().catch(() => ({}));
    } catch (e) {
      d = { error: "network" };
    }
    if (!r || !r.ok) {
      btn.disabled = false;
      btn.textContent = t("mm.compile");
      showError(d);
      return;
    }
    renderRunning({ status: "queued", position: d.position, project: d.project });
    poll(d.job_id);
  }

  function showError(d) {
    const code = d.error || "network";
    const msg = t("err." + code, { limit: d.limit || "" });
    const box = $("mmResult");
    box.hidden = false;
    box.innerHTML = `<div class="card-h err">${esc(t("mm.status.failed"))}</div>
      <div class="card-b"><div class="box err"><p>${esc(msg === "err." + code ? code : msg)}</p>${d.detail ? `<p class="mono small" style="margin-top:6px">${esc(d.detail)}</p>` : ""}</div></div>`;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function poll(id, onDone) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      let d;
      try {
        const r = await fetch(BASE + "/api/jobs/" + id, { cache: "no-store" });
        d = await r.json();
        if (!r.ok) { showError(d); resetBtn(); return; }
      } catch (e) { poll(id, onDone); return; }
      if (d.status === "success" || d.status === "failed") {
        resetBtn();
        if (onDone) { onDone(id, d); return; }
        lastResult = { id, d };
        renderDone(id, d);
      } else {
        renderRunning(d, !!onDone);
        poll(id, onDone);
      }
    }, 1500);
  }

  function resetBtn() {
    const btn = $("mmCompileBtn");
    btn.disabled = false;
    btn.textContent = t("mm.compile");
  }

  function steps(active, failed) {
    const order = ["queued", "fetch", "build", "done"];
    const idx = order.indexOf(active);
    return `<div class="steps">${order.map((s, i) => {
      let cls = "";
      if (i < idx || (active === "done" && !failed)) cls = "done";
      if (i === idx && active !== "done") cls = failed ? "failed" : "active";
      if (active === "done" && i === idx) cls = failed ? "failed" : "done";
      return `<span class="step ${cls}">${esc(t("mm.step." + s))}</span>`;
    }).join("")}</div>`;
  }

  function renderRunning(d, loading) {
    const box = $("mmResult");
    box.hidden = false;
    const st = d.status;
    const active = st === "fetching" ? "fetch" : st === "building" ? "build" : "queued";
    const label = st === "queued" ? t("mm.status.queued", { n: d.position || 1 }) : (loading ? t("mm.loading") : t("mm.status." + st));
    box.innerHTML = `<div class="card-h">${esc(label)}<span class="spacer"></span><span class="muted small">${esc(d.project || "")}</span></div>
      <div class="card-b">${steps(active, false)}<div class="progress"><i></i></div></div>`;
  }

  function renderDone(id, d) {
    const box = $("mmResult");
    box.hidden = false;
    if (d.expired || !d.result) {
      const failed = d.status === "failed";
      box.innerHTML = `<div class="card-h ${failed ? "err" : "warn"}">${esc(t(failed ? "mm.status.failed" : "mm.expired"))}</div><div class="card-b"><p class="muted">${esc(d.summary || "")}</p></div>`;
      return;
    }
    const r = d.result;
    const ok = r.success;
    let html = `<div class="card-h ${ok ? "ok" : "err"}">${esc(t(ok ? "mm.status.success" : "mm.status.failed"))}
      <span class="spacer"></span><span class="muted small">${esc(r.assembly || "")}</span></div><div class="card-b">`;
    const failedAt = !ok && /__STEP_FAILED__|== configure|== ambuild/.test(r.log) ? "build" : (!ok && r.hints.includes("git_clone_failed") ? "fetch" : "build");
    html += steps(ok ? "done" : failedAt, !ok);
    html += `<div class="meta-row small muted">
      <span>${esc(t("mm.duration"))}: <b>${esc(r.duration)} s</b></span>
      <span>${esc(t("mm.errors"))}: <b>${r.errors.length}</b></span>
      <span>${esc(t("mm.warnings"))}: <b>${r.warning_count || 0}</b></span>
      <span>${esc(t("mm.rt." + r.runtime))} · ${esc(r.configuration)}</span>
    </div>`;
    if (ok && d.downloadable) {
      html += `<a class="btn btn-primary" href="${esc(BASE)}/api/jobs/${esc(id)}/download">${esc(t("mm.download"))}</a>
        <p class="help" style="margin:8px 0 12px">${esc(t("mm.install"))}</p>`;
    }
    if (r.hints && r.hints.length) {
      html += `<div class="box ${ok ? "warn" : "err"}"><b>${esc(t("mm.hints"))}</b><ul>${r.hints.map((h) => `<li>${esc(t("hint." + h) === "hint." + h ? h : t("hint." + h))}</li>`).join("")}</ul></div>`;
    }
    if (r.errors.length) {
      html += `<div class="diag-wrap"><table class="diag"><thead><tr><th>${esc(t("mm.where"))}</th><th></th><th>${esc(t("mm.message"))}</th></tr></thead><tbody>${
        r.errors.slice(0, 60).map((e) => `<tr><td class="loc">${e.file && P && findFile(e.file)
          ? `<button type="button" class="mm-goto" data-file="${esc(e.file)}" data-line="${esc(e.line || "")}">${esc(e.file + (e.line ? ":" + e.line : ""))}</button>`
          : esc(e.file ? e.file + (e.line ? ":" + e.line : "") : "–")}</td><td class="code">${esc(e.code)}</td><td>${esc(e.message)}</td></tr>`).join("")
      }</tbody></table></div>`;
    }
    if (ok && r.files && r.files.length) {
      html += `<details class="mm-files"><summary>${esc(t("mm.files"))} (${r.files.length})</summary><ul class="mono small">${
        r.files.map((f) => `<li>${esc(f.path)} <span class="muted">${esc(fmtSize(f.size))}</span></li>`).join("")}</ul></details>`;
    }
    html += `<details class="mm-log"${!ok && !r.errors.length ? " open" : ""}><summary>${esc(t("mm.log"))}</summary><pre class="log">${esc(r.log || "")}</pre></details>`;
    html += `</div>`;
    box.innerHTML = html;
    box.querySelectorAll(".mm-goto").forEach((b) => b.addEventListener("click", () => gotoLine(b.dataset.file, +b.dataset.line || 0)));
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ---- Editor (ab 1.3.0) -------------------------------------------------------
  const TEXT_EXT = /\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inc|inl|ipp|tpp|proto|py|ambuild|json|jsonc|txt|md|cfg|ini|vdf|yml|yaml|toml|xml|sh|bat|cmake|lua|gitmodules|gitignore|kv|kv3|vcxproj|filters|sln)$/i;
  const TEXT_NAMES = /(^|\/)(AMBuildScript|AMBuilder|PackageScript|LICENSE|Makefile|README|\.gitmodules|\.gitignore)$/;
  const SRC_EXT = /\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inc|inl|ipp|tpp|proto)$/i;
  const BUILD_FILE = /(^|\/)(configure\.py|AMBuildScript|AMBuilder|PackageScript|plugin-metadata\.json|[^/]+\.ambuild)$/i;
  const MAX_FILES = 6000;

  function isText(path, bytes) {
    if (TEXT_EXT.test(path) || TEXT_NAMES.test(path)) return bytes.length < 3 * 1048576;
    if (bytes.length > 512 * 1024) return false;
    const n = Math.min(bytes.length, 8000);
    for (let i = 0; i < n; i++) if (bytes[i] === 0) return false;
    return true;
  }

  async function loadZip(buf, name) {
    let zip;
    try { zip = await JSZip.loadAsync(buf); } catch (e) { toast(t("mm.zipLoadFailed")); return false; }
    const entries = Object.values(zip.files).filter((f) => !f.dir);
    // gemeinsamen Wurzelordner (z. B. "Projekt-main/") entfernen
    const firsts = new Set(entries.map((f) => f.name.split("/")[0]));
    const strip = firsts.size === 1 && entries.every((f) => f.name.includes("/")) ? [...firsts][0] + "/" : "";
    const files = new Map();
    let skipped = 0;
    const dec = new TextDecoder("utf-8");
    for (const f of entries) {
      let path = f.name.replace(/\\/g, "/");
      if (strip && path.startsWith(strip)) path = path.slice(strip.length);
      const parts = path.split("/");
      if (!path || parts.some((x) => x === ".." || x === "") || parts.some((x) => x === ".git" || x === "__MACOSX") || parts[0] === "build") { skipped++; continue; }
      if (files.size >= MAX_FILES) { skipped++; continue; }
      const bytes = await f.async("uint8array");
      if (isText(path, bytes)) files.set(path, { text: dec.decode(bytes), bin: null, size: bytes.length });
      else files.set(path, { text: null, bin: bytes, size: bytes.length });
    }
    if (!files.size) { toast(t("err.zip_empty")); return false; }
    const subs = [];
    const gm = files.get(".gitmodules");
    if (gm && gm.text) {
      const re = /^\s*path\s*=\s*(.+?)\s*$/gm;
      let m;
      while ((m = re.exec(gm.text))) subs.push(m[1].replace(/\/+$/, ""));
    }
    P = { files, name: name || "plugin", current: null, cm: null, dirty: false, subs, skipped };
    P.current = pickInitial();
    showProject();
    return true;
  }

  function pickInitial() {
    const paths = [...P.files.keys()].sort();
    return paths.find((p) => /\.cpp$/i.test(p) && !inSub(p) && !p.includes("/"))
      || paths.find((p) => SRC_EXT.test(p) && !inSub(p))
      || paths.find((p) => /configure\.py$/.test(p)) || paths[0];
  }

  const inSub = (p) => P.subs.some((s) => p === s || p.startsWith(s + "/"));

  function showProject() {
    $("mmProject").hidden = false;
    $("mmInfo").hidden = true;
    $("mmProjectName").textContent = "· " + P.name;
    $("mmEditorNote").hidden = false;
    $("mmEditorNoteText").textContent = t("mm.fromEditor", { name: P.name });
    const banners = [];
    const hasBuild = P.files.has("configure.py") && P.files.has("AMBuildScript");
    if (!hasBuild) banners.push(`<div class="banner warn">${esc(t("err.mm_no_ambuild"))}</div>`);
    if (P.skipped) banners.push(`<div class="banner info">${esc(t("mm.skipped", { n: P.skipped }))}</div>`);
    $("mmBanners").innerHTML = banners.join("");
    renderTree();
    openFile(P.current);
    markDirty(P.dirty);
  }

  function closeProject(force) {
    if (!P) return;
    if (!force && P.dirty && !confirm(t("mm.closeConfirm"))) return;
    P = null;
    file = null;
    $("mmFileName").textContent = "";
    $("mmProject").hidden = true;
    $("mmInfo").hidden = false;
    $("mmEditorNote").hidden = true;
  }

  function markDirty(on) {
    if (!P) return;
    P.dirty = on;
    const m = $("mmModified");
    m.textContent = on ? t("mm.modified") : "";
    m.classList.toggle("dirty", on);
  }

  function renderTree() {
    const paths = [...P.files.keys()].sort((a, b) => a.localeCompare(b));
    const main = paths.filter((p) => !inSub(p));
    const subsFiles = paths.filter(inSub);
    const src = main.filter((p) => SRC_EXT.test(p));
    const build = main.filter((p) => !SRC_EXT.test(p) && BUILD_FILE.test(p));
    const other = main.filter((p) => !SRC_EXT.test(p) && !BUILD_FILE.test(p));
    const ico = (p) => (/\.(h|hh|hpp|hxx)$/i.test(p) ? "H" : SRC_EXT.test(p) ? "C+" : /\.py$|AMBuild|AMBuilder|PackageScript/.test(p) ? "⚙" : /\.json$/i.test(p) ? "{}" : P.files.get(p).text === null ? "■" : "≡");
    const btn = (p) => `<button type="button" data-path="${esc(p)}" class="${p === P.current ? "active" : ""}" title="${esc(p)}"><span class="ico">${ico(p)}</span><span>${esc(p.split("/").pop())}</span><span class="sz">${p.includes("/") ? esc(p.split("/").slice(-2, -1)[0]) : ""}</span></button>`;
    let html = "";
    if (src.length) html += `<div class="group">${esc(t("mm.group.source"))}</div>` + src.map(btn).join("");
    if (build.length) html += `<div class="group">${esc(t("mm.group.build"))}</div>` + build.map(btn).join("");
    if (other.length) html += `<div class="group">${esc(t("mm.group.other"))}</div>` + other.map(btn).join("");
    if (subsFiles.length) html += `<details class="subs"><summary>${esc(t("mm.group.submodules", { n: subsFiles.length }))}</summary>${subsFiles.slice(0, 1500).map(btn).join("")}</details>`;
    const tree = $("mmTree");
    tree.innerHTML = html;
    tree.querySelectorAll("button[data-path]").forEach((b) => b.addEventListener("click", () => openFile(b.dataset.path)));
  }

  function modeFor(p) {
    if (SRC_EXT.test(p)) return "text/x-c++src";
    if (/\.jsonc?$/i.test(p)) return { name: "javascript", json: true };
    if (/\.(xml|vcxproj|filters)$/i.test(p)) return "xml";
    return null;
  }

  function openFile(path) {
    const ed = $("mmEditor");
    P.current = path && P.files.has(path) ? path : null;
    $("mmEditorPath").textContent = P.current || "";
    $("mmDeleteFile").hidden = !P.current;
    document.querySelectorAll("#mmTree button[data-path]").forEach((b) => b.classList.toggle("active", b.dataset.path === P.current));
    if (!P.current) { P.cm = null; ed.innerHTML = `<div class="placeholder">${esc(t("mm.select"))}</div>`; return; }
    const f = P.files.get(P.current);
    if (f.text === null) { P.cm = null; ed.innerHTML = `<div class="placeholder">${esc(t("mm.binary", { size: fmtSize(f.size) }))}</div>`; return; }
    ed.innerHTML = "";
    const tabs = /^\t/m.test(f.text) && !/^ {2,}\S/m.test(f.text);
    P.cm = CodeMirror(ed, {
      value: f.text,
      mode: modeFor(P.current),
      lineNumbers: true,
      matchBrackets: true,
      autoCloseBrackets: true,
      styleActiveLine: true,
      indentUnit: tabs ? 4 : 2,
      tabSize: 4,
      indentWithTabs: tabs,
      extraKeys: { "Ctrl-Enter": () => compile(), "Cmd-Enter": () => compile() },
    });
    const cur = P.current;
    P.cm.on("change", (cm) => {
      const file = P && P.files.get(cur);
      if (!file) return;
      file.text = cm.getValue();
      file.size = file.text.length;
      markDirty(true);
    });
  }

  function findFile(path) {
    if (!P) return null;
    if (P.files.has(path)) return path;
    return [...P.files.keys()].find((p) => p.endsWith("/" + path) || path.endsWith("/" + p)) || null;
  }

  function gotoLine(path, line) {
    const f = findFile(path);
    if (!f) return;
    if (inSub(f)) { const d = document.querySelector("#mmTree details.subs"); if (d) d.open = true; }
    openFile(f);
    if (P.cm && line) {
      P.cm.addLineClass(line - 1, "background", "cm-err-line");
      P.cm.setCursor({ line: line - 1, ch: 0 });
      P.cm.scrollIntoView({ line: line - 1, ch: 0 }, 120);
      P.cm.focus();
    }
    $("mmProject").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function newFile() {
    if (!P) return;
    const base = P.current && P.current.includes("/") ? P.current.split("/").slice(0, -1).join("/") + "/" : "";
    let path = prompt(t("mm.newFilePrompt"), base + "neu.cpp");
    if (!path) return;
    path = path.trim().replace(/\\/g, "/").replace(/^\/+/, "");
    if (!path || path.split("/").some((x) => !x || x === "..")) { toast(t("err.zip_unsafe")); return; }
    if (!P.files.has(path)) P.files.set(path, { text: "", bin: null, size: 0 });
    markDirty(true);
    renderTree();
    openFile(path);
  }

  function deleteFile() {
    if (!P || !P.current || !confirm(t("mm.deleteConfirm", { path: P.current }))) return;
    P.files.delete(P.current);
    markDirty(true);
    P.current = pickInitial();
    renderTree();
    openFile(P.current);
  }

  function projectZip() {
    const zip = new JSZip();
    for (const [p, f] of P.files) zip.file(p, f.text !== null ? f.text : f.bin);
    return zip.generateAsync({ type: "blob", compression: "DEFLATE", compressionOptions: { level: 6 } });
  }

  async function exportZip() {
    if (!P) return;
    const blob = await projectZip();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (P.name || "plugin") + "_source.zip";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1500);
    markDirty(false);
  }

  async function openRepoInEditor() {
    const url = $("mmGitUrl").value.trim();
    if (!url) { toast(t("err.mm_no_source")); $("mmGitUrl").focus(); return; }
    if (P && P.dirty && !confirm(t("mm.closeConfirm"))) return;
    const btn = $("mmOpenEditor");
    btn.disabled = true;
    let r, d;
    try {
      r = await fetch(BASE + "/api/metamod/fetch", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ git_url: url, git_ref: $("mmGitRef").value.trim() }),
      });
      d = await r.json().catch(() => ({}));
    } catch (e) { d = { error: "network" }; }
    if (!r || !r.ok) { btn.disabled = false; showError(d); return; }
    renderRunning({ status: "queued", position: d.position, project: d.project }, true);
    poll(d.job_id, async (id, res) => {
      btn.disabled = false;
      const box = $("mmResult");
      if (res.status !== "success" || !res.source_available) {
        lastResult = { id, d: res };
        renderDone(id, res);
        return;
      }
      try {
        const zr = await fetch(BASE + "/api/jobs/" + id + "/source");
        if (!zr.ok) throw new Error("expired");
        const ok = await loadZip(await zr.arrayBuffer(), (res.result && res.result.assembly) || d.project);
        if (!ok) return;
        box.hidden = false;
        box.innerHTML = `<div class="card-h ok">${esc(t("mm.loaded", { n: P.files.size }))}<span class="spacer"></span><span class="muted small">${esc(P.name)}</span></div>`;
        lastResult = null;
        $("mmProject").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (e) {
        showError({ error: "expired" });
      }
    });
  }

  // ---- Start -----------------------------------------------------------------
  document.addEventListener("siteinfo", (e) => {
    info = e.detail;
    if (!info.metamod_enabled) return;
    $("modeTabs").hidden = false;
    fillRuntimes();
    helpTexts();
    const want = (location.hash === "#metamod" ? "metamod" : store.get("cssc.mode", "cssharp"));
    setMode(want, false);
  });

  document.addEventListener("langchange", () => {
    if (!info) return;
    fillRuntimes();
    helpTexts();
    if (lastResult) renderDone(lastResult.id, lastResult.d);
    if (P) { renderTree(); $("mmEditorNoteText").textContent = t("mm.fromEditor", { name: P.name }); markDirty(P.dirty); }
    if (!$("mmCompileBtn").disabled) $("mmCompileBtn").textContent = t("mm.compile");
  });

  async function checkReady() {
    if (!info || !info.metamod_enabled) return;
    try {
      const r = await fetch(BASE + "/api/status", { cache: "no-store" });
      const s = await r.json();
      mmReady = s.metamod === "running";
      $("mmNotReady").hidden = mmReady;
    } catch (e) { /* egal */ }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".mode[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode, true)));
    document.querySelectorAll('input[name="mmSource"]').forEach((i) => i.addEventListener("change", updateSource));
    updateSource();
    $("mmExample").addEventListener("click", () => { $("mmGitUrl").value = EXAMPLE; $("mmGitRef").value = ""; });
    $("mmFile").addEventListener("change", (e) => setFile(e.target.files[0]));
    const drop = $("mmDrop");
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));
    $("mmCompileBtn").addEventListener("click", compile);
    $("mmOpenEditor").addEventListener("click", openRepoInEditor);
    $("mmNewFile").addEventListener("click", newFile);
    $("mmDeleteFile").addEventListener("click", deleteFile);
    $("mmExport").addEventListener("click", exportZip);
    $("mmClose").addEventListener("click", () => closeProject(false));
    window.addEventListener("beforeunload", (e) => { if (P && P.dirty) { e.preventDefault(); e.returnValue = ""; } });
    $("mmGitUrl").addEventListener("keydown", (e) => { if (e.key === "Enter") compile(); });
    setTimeout(checkReady, 800);
    setInterval(checkReady, 15000);
  });
})();
