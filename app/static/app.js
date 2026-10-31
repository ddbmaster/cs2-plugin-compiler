/* CS2 Plugin Compiler – Hauptseite */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const TEXT_EXT = /\.(cs|csproj|props|targets|proj|sln|slnx|json|jsonc|xml|config|txt|md|yml|yaml|toml|ini|cfg|editorconfig|gitignore|gitattributes|resx|razor|sql|sh|bat|ps1|lang|phrases|vdf|kv)$/i;
  const SKIP_SEG = new Set(["bin", "obj", ".git", ".vs", ".idea", ".vscode", "node_modules", "__macosx"]);
  const MAX_EDIT_SIZE = 2 * 1024 * 1024;

  const S = {
    files: new Map(),        // Pfad -> { text: string|null, bin: Uint8Array|null, size }
    name: "",
    isDemo: true,
    current: null,
    versions: [],
    latest: null,
    cm: null,
    errLines: [],
    busy: false,
    pollTimer: null,
    lastRequest: null,
    quiet: false,
    treeOpen: false,
  };

  // --------------------------------------------------------------------- //
  // Demo-Projekt
  // --------------------------------------------------------------------- //
  function demoFiles(tf, ver) {
    return {
      "DemoPlugin/DemoPlugin.csproj":
`<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>${tf || "net8.0"}</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="CounterStrikeSharp.API" Version="${ver || "*"}" ExcludeAssets="runtime" />
  </ItemGroup>

</Project>
`,
      "DemoPlugin/DemoPlugin.cs":
`using CounterStrikeSharp.API.Core;
using CounterStrikeSharp.API.Core.Attributes.Registration;
using CounterStrikeSharp.API.Modules.Commands;

namespace DemoPlugin;

public class DemoPlugin : BasePlugin
{
    public override string ModuleName => "Demo Plugin";
    public override string ModuleVersion => "1.0.0";
    public override string ModuleAuthor => "ddbmaster.com";
    public override string ModuleDescription => "Hallo-Welt-Beispiel";

    public override void Load(bool hotReload)
    {
        Console.WriteLine("[DemoPlugin] geladen!");
    }

    [ConsoleCommand("css_hallo", "Sagt Hallo")]
    public void OnHallo(CCSPlayerController? player, CommandInfo command)
    {
        command.ReplyToCommand($"Hallo {player?.PlayerName ?? "Konsole"}!");
    }
}
`,
    };
  }

  function loadDemo() {
    const entry = selectedVersionEntry();
    const tf = entry && entry.frameworks && entry.frameworks[0];
    S.files.clear();
    const d = demoFiles(tf, entry ? entry.version : null);
    for (const p in d) S.files.set(p, { text: d[p], bin: null, size: d[p].length });
    S.name = t("project.demo");
    S.isDemo = true;
    S.current = "DemoPlugin/DemoPlugin.cs";
    $("fileName").textContent = "";
    $("fileInput").value = "";
    afterProjectChange();
  }

  function syncDemoFramework() {
    if (!S.isDemo) return;
    const entry = selectedVersionEntry();
    const f = S.files.get("DemoPlugin/DemoPlugin.csproj");
    if (!entry || !f || !f.text) return;
    let txt = f.text;
    if (entry.frameworks && entry.frameworks[0]) txt = txt.replace(/<TargetFramework>[^<]*<\/TargetFramework>/, `<TargetFramework>${entry.frameworks[0]}</TargetFramework>`);
    txt = txt.replace(/(Include="CounterStrikeSharp\.API"\s+Version=")[^"]*"/, `$1${entry.version}"`);
    if (txt !== f.text) {
      f.text = txt; f.size = txt.length;
      if (S.current === "DemoPlugin/DemoPlugin.csproj" && S.cm) { S.quiet = true; S.cm.setValue(txt); S.quiet = false; }
      saveProject();
    }
  }

  // --------------------------------------------------------------------- //
  // Projekt laden / speichern
  // --------------------------------------------------------------------- //
  function skipPath(path) {
    const parts = path.split("/").filter(Boolean);
    if (!parts.length) return true;
    if (parts.slice(0, -1).some((p) => SKIP_SEG.has(p.toLowerCase()))) return true;
    const last = parts[parts.length - 1].toLowerCase();
    return last === ".ds_store" || last === "thumbs.db" || last === "desktop.ini";
  }

  function looksText(bytes) {
    const n = Math.min(bytes.length, 8000);
    for (let i = 0; i < n; i++) if (bytes[i] === 0) return false;
    return true;
  }

  async function loadZip(file) {
    const limit = ((window.SITE_INFO && window.SITE_INFO.max_upload_mb) || 20) * 1024 * 1024;
    if (file.size > limit) { toast(t("err.upload_too_big", { limit: limit / 1048576 })); return; }
    let zip;
    try { zip = await JSZip.loadAsync(file); } catch (e) { toast(t("project.loadFailed")); return; }
    const files = new Map();
    let skipped = 0;
    const entries = [];
    zip.forEach((path, entry) => { if (!entry.dir) entries.push([path.replace(/\\/g, "/"), entry]); });
    for (const [path, entry] of entries) {
      if (skipPath(path)) { skipped++; continue; }
      const bin = await entry.async("uint8array");
      if ((TEXT_EXT.test(path) || looksText(bin)) && bin.length <= MAX_EDIT_SIZE && looksText(bin)) {
        let text = new TextDecoder("utf-8").decode(bin);
        files.set(path, { text, bin: null, size: bin.length });
      } else {
        files.set(path, { text: null, bin, size: bin.length });
      }
    }
    S.files = files;
    S.name = file.name;
    S.isDemo = false;
    S.current = pickInitialFile();
    $("fileName").textContent = file.name;
    afterProjectChange(skipped);
  }

  function pickInitialFile() {
    const paths = [...S.files.keys()];
    const cs = paths.filter((p) => /\.cs$/i.test(p)).sort((a, b) => a.split("/").length - b.split("/").length);
    return cs[0] || paths.find((p) => /\.csproj$/i.test(p)) || paths[0] || null;
  }

  function saveProject() {
    let total = 0;
    const out = {};
    for (const [p, f] of S.files) {
      if (f.text === null) { setSaved(false); try { localStorage.removeItem("cssc.project"); } catch (e) {} return; }
      total += f.text.length;
      out[p] = f.text;
    }
    if (total > 1.5 * 1024 * 1024) { setSaved(false); return; }
    store.set("cssc.project", JSON.stringify({ name: S.name, isDemo: S.isDemo, current: S.current, files: out }));
    setSaved(true);
  }

  function setSaved(ok) {
    const el = $("savedInfo");
    el.dataset.i18n = ok ? "project.saved" : "project.savedLocal";
    el.textContent = t(el.dataset.i18n);
  }

  function restoreProject() {
    try {
      const raw = store.get("cssc.project", null);
      if (!raw) return false;
      const d = JSON.parse(raw);
      if (!d || !d.files || !Object.keys(d.files).length) return false;
      S.files = new Map(Object.entries(d.files).map(([p, txt]) => [p, { text: txt, bin: null, size: txt.length }]));
      S.name = d.isDemo ? t("project.demo") : d.name;
      S.isDemo = !!d.isDemo;
      S.current = S.files.has(d.current) ? d.current : pickInitialFile();
      return true;
    } catch (e) { return false; }
  }

  // --------------------------------------------------------------------- //
  // Baum + Editor
  // --------------------------------------------------------------------- //
  function csprojList() {
    return [...S.files.keys()].filter((p) => /\.csproj$/i.test(p)).sort();
  }

  function packagesOf() {
    const pk = new Map();
    for (const p of csprojList()) {
      const txt = S.files.get(p).text || "";
      const re = /<PackageReference\b([^>]*)>/gi;
      let m;
      while ((m = re.exec(txt))) {
        const inc = /\bInclude\s*=\s*"([^"]+)"/i.exec(m[1]);
        const ver = /\bVersion\s*=\s*"([^"]*)"/i.exec(m[1]);
        if (inc) pk.set(inc[1], ver ? ver[1] : "");
      }
    }
    return pk;
  }

  function afterProjectChange(skipped) {
    // Hauptprojekt-Auswahl
    const cps = csprojList();
    const sel = $("csprojSel");
    const prev = sel.value;
    sel.innerHTML = cps.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
    if (cps.includes(prev)) sel.value = prev;
    $("csprojField").hidden = cps.length < 2;

    // Hinweise
    const banners = [];
    if (!cps.length && S.files.size) {
      banners.push(`<div class="banner warn">${esc(t("project.noCsproj"))} <button class="btn btn-ghost btn-sm" id="addCsprojBtn" type="button">${esc(t("project.addCsproj"))}</button></div>`);
    }
    if (skipped) banners.push(`<div class="banner info">${esc(t("project.skipped", { n: skipped }))}</div>`);
    $("projectBanners").innerHTML = banners.join("");
    const ab = $("addCsprojBtn");
    if (ab) ab.addEventListener("click", addDefaultCsproj);

    $("projectName").textContent = S.name ? "· " + S.name : "";
    renderTree();
    openFile(S.current);
    saveProject();
    applyTreeVisibility();
  }

  function renderTree() {
    const tree = $("tree");
    const paths = [...S.files.keys()].sort((a, b) => a.localeCompare(b));
    const isProj = (p) => /\.(cs|csproj|props|targets|sln|slnx)$/i.test(p);
    const proj = paths.filter(isProj);
    const other = paths.filter((p) => !isProj(p));
    const pk = packagesOf();
    const ico = (p) => (/\.cs$/i.test(p) ? "C#" : /\.csproj$/i.test(p) ? "⚙" : /\.json$/i.test(p) ? "{}" : S.files.get(p).text === null ? "■" : "≡");
    const btn = (p) => `<button type="button" data-path="${esc(p)}" class="${p === S.current ? "active" : ""}" title="${esc(p)}"><span class="ico">${ico(p)}</span><span>${esc(p.split("/").pop())}</span><span class="sz">${p.includes("/") ? esc(p.split("/").slice(-2, -1)[0]) : ""}</span></button>`;
    let html = "";
    if (pk.size) {
      html += `<div class="group">${esc(t("project.packages"))}</div>`;
      for (const [n, v] of pk) html += `<div class="pkg">${esc(n)}${v ? " <span class='muted'>" + esc(v) + "</span>" : ""}</div>`;
    }
    html += `<div class="group">${esc(t("project.files"))}</div>` + proj.map(btn).join("");
    if (other.length) html += `<div class="group">${esc(t("project.other"))}</div>` + other.map(btn).join("");
    tree.innerHTML = html;
    tree.querySelectorAll("button[data-path]").forEach((b) => b.addEventListener("click", () => openFile(b.dataset.path)));
  }

  function modeFor(p) {
    if (/\.cs$/i.test(p)) return "text/x-csharp";
    if (/\.(csproj|props|targets|proj|xml|config|resx)$/i.test(p)) return "xml";
    if (/\.jsonc?$/i.test(p)) return { name: "javascript", json: true };
    return null;
  }

  function openFile(path) {
    const ed = $("editor");
    S.current = path && S.files.has(path) ? path : null;
    $("editorPath").textContent = S.current || "";
    $("deleteFileBtn").hidden = !S.current;
    document.querySelectorAll("#tree button[data-path]").forEach((b) => b.classList.toggle("active", b.dataset.path === S.current));
    if (!S.current) {
      S.cm = null;
      ed.innerHTML = `<div class="placeholder">${esc(t("project.select"))}</div>`;
      return;
    }
    const f = S.files.get(S.current);
    if (f.text === null) {
      S.cm = null;
      ed.innerHTML = `<div class="placeholder">${esc(t("project.binary", { size: fmtSize(f.size) }))}</div>`;
      return;
    }
    ed.innerHTML = "";
    S.errLines = [];
    S.cm = CodeMirror(ed, {
      value: f.text,
      mode: modeFor(S.current),
      lineNumbers: true,
      matchBrackets: true,
      autoCloseBrackets: true,
      styleActiveLine: true,
      indentUnit: 4,
      tabSize: 4,
      indentWithTabs: false,
      lineWrapping: false,
      extraKeys: { "Ctrl-Enter": () => compile(), "Cmd-Enter": () => compile() },
    });
    let timer;
    const cur = S.current;
    S.cm.on("change", (cm) => {
      const file = S.files.get(cur);
      if (!file) return;
      file.text = cm.getValue();
      file.size = file.text.length;
      if (S.isDemo && !S.quiet) { S.isDemo = false; S.name = t("project.demo"); }
      clearTimeout(timer);
      timer = setTimeout(() => { saveProject(); if (/\.csproj$/i.test(cur)) renderTree(); }, 600);
    });
    saveProject();
  }

  function gotoLine(path, line) {
    S.treeOpen = true; applyTreeVisibility();
    if (!S.files.has(path)) {
      const alt = [...S.files.keys()].find((p) => p.endsWith("/" + path) || path.endsWith("/" + p));
      if (!alt) return;
      path = alt;
    }
    openFile(path);
    if (S.cm && line) {
      S.cm.addLineClass(line - 1, "background", "cm-err-line");
      S.cm.setCursor({ line: line - 1, ch: 0 });
      S.cm.scrollIntoView({ line: line - 1, ch: 0 }, 120);
      S.cm.focus();
    }
    $("projectCard").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function addDefaultCsproj() {
    const cs = [...S.files.keys()].filter((p) => /\.cs$/i.test(p));
    const dir = cs.length ? cs[0].split("/").slice(0, -1).join("/") : "";
    let name = "MyPlugin";
    for (const p of cs) {
      const m = /class\s+(\w+)\s*:\s*BasePlugin/.exec(S.files.get(p).text || "");
      if (m) { name = m[1]; break; }
    }
    const entry = selectedVersionEntry();
    const tf = (entry && entry.frameworks && entry.frameworks[0]) || "net8.0";
    const path = (dir ? dir + "/" : "") + name + ".csproj";
    const txt = demoFiles(tf, entry ? entry.version : "*")["DemoPlugin/DemoPlugin.csproj"];
    S.files.set(path, { text: txt, bin: null, size: txt.length });
    S.current = path;
    afterProjectChange();
  }

  function applyTreeVisibility() {
    // „Projektstruktur immer anzeigen“ aus: Explorer eingeklappt, Klick auf die Überschrift klappt auf
    const show = $("optTree").checked || S.treeOpen;
    $("explorer").hidden = !show;
    $("treeToggle").textContent = show ? "▾" : "▸";
    if (show && S.cm) S.cm.refresh();
  }

  // --------------------------------------------------------------------- //
  // Versionen
  // --------------------------------------------------------------------- //
  function selectedVersionEntry() {
    const v = $("versionSel").value;
    if (v === "latest") return S.versions.find((e) => e.version === S.latest) || null;
    return S.versions.find((e) => e.version === v) || null;
  }

  function renderVersions(filter) {
    const sel = $("versionSel");
    const prev = sel.value || store.get("cssc.version", "latest");
    const f = (filter || "").trim().toLowerCase();
    let html = "";
    if (!S.versions.length) {
      html = `<option value="latest">${esc(t("settings.versionsFailed"))}</option><option value="project">${esc(t("settings.fromProject"))}</option>`;
    } else {
      const latestEntry = S.versions.find((e) => e.version === S.latest);
      html += `<option value="latest">${esc(t("settings.latest", { v: S.latest }))}${latestEntry && latestEntry.frameworks.length ? " · " + esc(latestEntry.frameworks.map(tfLabel).join(", ")) : ""}</option>`;
      html += `<option value="project">${esc(t("settings.fromProject"))}</option>`;
      for (const e of S.versions) {
        if (f && !e.version.toLowerCase().includes(f)) continue;
        html += `<option value="${esc(e.version)}">CounterStrikeSharp ${esc(e.version)}${e.frameworks.length ? " · " + esc(e.frameworks.map(tfLabel).join(", ")) : ""}${e.prerelease ? " (pre)" : ""}</option>`;
      }
    }
    sel.innerHTML = html;
    if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
    else if (f && sel.options.length > 2) sel.selectedIndex = 2;
  }

  async function loadVersions() {
    try {
      const r = await fetch(BASE + "/api/versions");
      const d = await r.json();
      S.versions = d.versions || [];
      S.latest = d.latest;
    } catch (e) {
      S.versions = [];
    }
    renderVersions();
    syncDemoFramework();
  }

  // --------------------------------------------------------------------- //
  // Kompilieren
  // --------------------------------------------------------------------- //
  function setBusy(on, labelKey) {
    S.busy = on;
    const b = $("compileBtn");
    b.disabled = on;
    b.textContent = t(on ? labelKey : "settings.compile");
  }

  const STEPS = ["upload", "queue", "restore", "build", "done"];
  function stepsHtml(active, failed, pos) {
    const idx = STEPS.indexOf(active);
    return `<div class="steps">` + STEPS.map((s, i) => {
      let cls = "", inner = "";
      if (i < idx) cls = "done";
      else if (i === idx) cls = failed ? "failed" : (s === "done" ? "done" : "active");
      if (i === idx && !failed && s !== "done") inner = `<span class="spin"></span>`;
      const label = s === "queue" && pos ? t("result.queuePos", { n: pos }) : t({ upload: "result.upload", queue: "result.queue", restore: "result.restore", build: "result.build", done: "result.done" }[s]);
      return `<span class="step ${cls}">${inner}${esc(label)}</span>`;
    }).join("") + `</div>`;
  }

  function showResult(html) {
    const r = $("result");
    r.innerHTML = html;
    r.hidden = false;
  }

  function showProgress(step, pos) {
    showResult(`<div class="card-h">${esc(t("result.title"))}</div><div class="card-b">${stepsHtml(step, false, pos)}</div>`);
  }

  async function compile(extra) {
    if (S.busy) return;
    if (!S.files.size) { loadDemo(); }
    if (!csprojList().length) { toast(t("err.no_csproj")); return; }
    extra = extra || {};
    setBusy(true, "settings.uploading");
    showProgress("upload");
    $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });

    try {
      const zip = new JSZip();
      for (const [p, f] of S.files) zip.file(p, f.text !== null ? f.text : f.bin);
      const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE", compressionOptions: { level: 6 } });
      const fd = new FormData();
      fd.append("file", blob, "project.zip");
      fd.append("api_version", extra.api_version || $("versionSel").value || "latest");
      fd.append("configuration", document.querySelector("input[name=cfg]:checked").value);
      if (csprojList().length > 1) fd.append("csproj", $("csprojSel").value);
      if (extra.retarget) fd.append("retarget", extra.retarget);
      S.lastRequest = extra;

      const r = await fetch(BASE + "/api/compile", { method: "POST", body: fd });
      let d;
      try { d = await r.json(); } catch (e) { d = { error: r.status === 413 ? "upload_too_big" : "network" }; }
      if (!r.ok || d.error) {
        renderError(d);
        setBusy(false);
        return;
      }
      if (d.status === "mismatch") {
        renderMismatch(d);
        setBusy(false);
        return;
      }
      setBusy(true, "settings.compiling");
      showProgress("queue", d.position);
      poll(d.job_id, d);
    } catch (e) {
      renderError({ error: "network" });
      setBusy(false);
    }
  }

  function poll(jobId, initial) {
    clearTimeout(S.pollTimer);
    const tick = async () => {
      let d;
      try {
        const r = await fetch(BASE + "/api/jobs/" + jobId, { cache: "no-store" });
        d = await r.json();
      } catch (e) { S.pollTimer = setTimeout(tick, 2500); return; }
      if (d.error) { renderError(d); setBusy(false); refreshStatus(); return; }
      if (d.status === "queued") showProgress("queue", d.position);
      else if (d.status === "restoring") showProgress("restore");
      else if (d.status === "building") showProgress("build");
      if (d.status === "success" || d.status === "failed") {
        renderFinal(jobId, d, initial);
        setBusy(false);
        refreshStatus();
        loadStats();
        return;
      }
      S.pollTimer = setTimeout(tick, 1200);
    };
    tick();
  }

  function noteText(n) {
    const i = n.indexOf(":");
    const key = i >= 0 ? n.slice(0, i) : n;
    const val = i >= 0 ? n.slice(i + 1).replace(">", " → ") : "";
    return t("note." + key, { x: val });
  }

  function renderError(d) {
    const msg = t("err." + (d.error || "network"), { limit: d.limit || "" });
    showResult(`<div class="card-h err">✕ ${esc(t("result.error"))}</div><div class="card-b">
      <div class="box err"><p>${esc(msg)}</p>${d.detail ? `<p class="mono small" style="margin-top:4px;opacity:.85">${esc(d.detail)}</p>` : ""}</div></div>`);
  }

  function renderMismatch(d) {
    const p = d.project || {};
    let html = `<div class="card-h warn">⚠ ${esc(t("result.mismatch"))}</div><div class="card-b">`;
    html += `<div class="box warn"><p>${esc(t("mismatch.text", { ptf: tfLabel(p.target_framework), v: d.api_version, pkg: (d.package_frameworks || []).map(tfLabel).join(", ") }))}</p></div>`;
    html += `<div class="actions">`;
    if (d.suggested_version) {
      html += `<button class="btn btn-primary" style="width:auto" id="mmVersion" type="button">${esc(t("mismatch.useVersion", { v: d.suggested_version, tf: tfLabel(p.target_framework) }))}</button>`;
    }
    if (d.retarget_framework) {
      html += `<button class="btn btn-ghost" id="mmRetarget" type="button">${esc(t("mismatch.retarget", { tf: tfLabel(d.retarget_framework) }))}</button>`;
    }
    html += `</div>`;
    if (!d.suggested_version && !d.retarget_framework) html += `<p class="muted">${esc(t("mismatch.none"))}</p>`;
    if (d.retarget_framework) html += `<p class="help">${esc(t("mismatch.retargetHint", { tf: tfLabel(d.retarget_framework) }))}</p>`;
    html += `</div>`;
    showResult(html);
    const a = $("mmVersion");
    if (a) a.addEventListener("click", () => {
      const sel = $("versionSel");
      $("versionSearch").value = "";
      renderVersions();
      sel.value = d.suggested_version;
      store.set("cssc.version", d.suggested_version);
      compile();
    });
    const b = $("mmRetarget");
    if (b) b.addEventListener("click", () => compile({ api_version: d.api_version, retarget: d.retarget_framework }));
  }

  function diagTable(list, warn) {
    if (!list.length) return "";
    const rows = list.slice(0, 100).map((e) => {
      const loc = e.file ? `${e.file}${e.line ? "(" + e.line + (e.col ? "," + e.col : "") + ")" : ""}` : "";
      const locHtml = loc ? `<button type="button" data-file="${esc(e.file)}" data-line="${e.line || ""}">${esc(loc.split("/").pop())}</button>` : "";
      return `<tr><td class="code ${warn ? "w" : ""}">${esc(e.code)}</td><td class="loc">${locHtml}</td><td>${esc(e.message)}</td></tr>`;
    }).join("");
    return `<div class="diag-wrap"><table class="diag"><thead><tr><th>${esc(t("result.diagCode"))}</th><th>${esc(t("result.diagFile"))}</th><th>${esc(t("result.diagMsg"))}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function logHtml(log) {
    return esc(log).split("\n").map((l) => (/: error [A-Z]+\d+/.test(l) ? `<span class="e">${l}</span>` : /: warning [A-Z]+\d+/.test(l) ? `<span class="w">${l}</span>` : l)).join("\n");
  }

  function renderFinal(jobId, d) {
    if (!d.result) {
      showResult(`<div class="card-h err">✕ ${esc(t("result.failed"))}</div><div class="card-b"><div class="box warn">${esc(t("result.expired"))}</div></div>`);
      return;
    }
    const r = d.result;
    const ok = r.success;
    let html = `<div class="card-h ${ok ? "ok" : "err"}">${ok ? "✓" : "✕"} ${esc(t(ok ? "result.success" : "result.failed"))}</div><div class="card-b">`;
    html += stepsHtml(ok ? "done" : (r.errors.length || r.log.includes("dotnet build") ? "build" : "restore"), !ok);
    html += `<div class="kv">
      <span>${esc(t("result.duration"))}: <b>${r.duration}s</b></span>
      <span>${esc(t("result.version"))}: <b>${esc(r.api_version || "?")}</b></span>
      <span>${esc(t("result.framework"))}: <b>${esc(tfLabel(r.framework))}</b></span>
      <span>${esc(t("result.config"))}: <b>${esc(r.configuration)}</b></span>
      <span>${esc(t("result.errors"))}: <b>${r.errors.length}</b></span>
      <span>${esc(t("result.warnings"))}: <b>${r.warning_count}</b></span>
    </div>`;

    if (ok) {
      html += `<div class="actions">${d.downloadable ? `<a class="btn btn-ok" href="${BASE}/api/jobs/${esc(jobId)}/download">⬇ ${esc(t("result.download"))}</a>` : `<span class="box warn">${esc(t("result.expired"))}</span>`}</div>`;
      html += `<div class="box ok"><p>${esc(t("result.install", { name: r.assembly }))}</p></div>`;
    }
    if (r.hints && r.hints.length) {
      html += `<div class="box ${ok ? "warn" : "err"}"><b>${esc(t("result.hints"))}</b><ul>${r.hints.map((h) => `<li>${esc(t("hint." + h))}</li>`).join("")}</ul></div>`;
    }
    if (r.notes && r.notes.length) {
      html += `<div class="box info"><b>${esc(t("result.notes"))}</b><ul>${r.notes.map((n) => `<li>${esc(noteText(n))}</li>`).join("")}</ul></div>`;
    }
    html += diagTable(r.errors, false);
    if (r.warnings.length) html += `<details><summary>${esc(t("result.warnings"))} (${r.warning_count})</summary><div style="padding:0 10px">${diagTable(r.warnings, true)}</div></details>`;
    if (ok && r.files.length) {
      html += `<details><summary>${esc(t("result.files"))} (${r.files.length})</summary><ul class="files" style="padding:0 12px 10px">${r.files.map((f) => `<li><span>${esc(f.path)}</span><span>${fmtSize(f.size)}</span></li>`).join("")}</ul></details>`;
    }
    const openLog = $("optLog").checked || (!ok && !r.errors.length);
    html += `<details ${openLog ? "open" : ""}><summary>${esc(t("result.log"))}</summary><pre class="log">${logHtml(r.log)}</pre></details>`;
    html += `</div>`;
    showResult(html);
    $("result").querySelectorAll(".diag td.loc button").forEach((b) => b.addEventListener("click", () => gotoLine(b.dataset.file, parseInt(b.dataset.line, 10) || 0)));
  }

  // --------------------------------------------------------------------- //
  // Statistik
  // --------------------------------------------------------------------- //
  async function loadStats() {
    let s;
    try { s = await (await fetch(BASE + "/api/stats", { cache: "no-store" })).json(); } catch (e) { return; }
    const card = (total, map, kind, key) => {
      const entries = Object.entries(map).sort((a, b) => {
        const ma = parseFloat((a[0].match(/\d+(\.\d+)?/) || [0])[0]); const mb = parseFloat((b[0].match(/\d+(\.\d+)?/) || [0])[0]);
        return mb - ma;
      });
      let html = `<div class="card"><div class="card-b"><div class="stat-num ${kind}">${total.toLocaleString(getLang())}</div><div class="muted">${esc(t(key))}</div>`;
      if (!entries.length) html += `<p class="muted small">${esc(t("stats.none"))}</p>`;
      for (const [tf, n] of entries) {
        const pct = total ? Math.round((n / total) * 100) : 0;
        html += `<div class="bar-row"><span>${esc(tfLabel(tf))}</span><div class="bar ${kind}"><i style="width:${pct}%"></i></div><span class="n">${n} · ${pct}%</span></div>`;
      }
      return html + `</div></div>`;
    };
    $("stats").innerHTML = card(s.total_success, s.success, "ok", "stats.ok") + card(s.total_failed, s.failed, "err", "stats.fail");
  }

  // --------------------------------------------------------------------- //
  // Ereignisse
  // --------------------------------------------------------------------- //
  function bind() {
    const drop = $("drop");
    const input = $("fileInput");
    // Nach dem Laden zurücksetzen, damit dieselbe Datei erneut gewählt werden kann
    input.addEventListener("change", async () => { const f = input.files[0]; if (f) { await loadZip(f); input.value = ""; } });
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) loadZip(f); });

    $("compileBtn").addEventListener("click", () => compile());
    $("demoBtn").addEventListener("click", loadDemo);
    $("versionSel").addEventListener("change", () => { store.set("cssc.version", $("versionSel").value); syncDemoFramework(); });
    $("versionSearch").addEventListener("input", (e) => renderVersions(e.target.value));

    $("newFileBtn").addEventListener("click", () => {
      const name = prompt(t("project.newPrompt"));
      if (!name) return;
      const clean = name.replace(/\\/g, "/").split("/").filter((p) => p && p !== "." && p !== "..").join("/");
      if (!clean) return;
      const base = S.current && S.current.includes("/") ? S.current.split("/").slice(0, -1).join("/") + "/" : "";
      const path = clean.includes("/") ? clean : base + clean;
      if (S.files.has(path)) { toast(t("project.exists")); return; }
      let txt = "";
      if (/\.cs$/i.test(path)) {
        const cls = path.split("/").pop().replace(/\.cs$/i, "").replace(/\W/g, "_");
        txt = `namespace ${S.isDemo ? "DemoPlugin" : "MyPlugin"};\n\npublic class ${cls}\n{\n}\n`;
      }
      S.files.set(path, { text: txt, bin: null, size: txt.length });
      S.current = path;
      afterProjectChange();
    });
    $("deleteFileBtn").addEventListener("click", () => {
      if (!S.current || !confirm(t("project.deleteConfirm", { f: S.current }))) return;
      S.files.delete(S.current);
      S.current = pickInitialFile();
      afterProjectChange();
    });
    $("exportBtn").addEventListener("click", async () => {
      const zip = new JSZip();
      for (const [p, f] of S.files) zip.file(p, f.text !== null ? f.text : f.bin);
      const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = (S.isDemo ? "DemoPlugin" : (S.name || "project").replace(/\.zip$/i, "")) + ".zip";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    });

    const optLog = $("optLog"), optTree = $("optTree");
    optLog.checked = store.get("cssc.optLog", "0") === "1";
    optTree.checked = store.get("cssc.optTree", "1") === "1";
    optLog.addEventListener("change", () => store.set("cssc.optLog", optLog.checked ? "1" : "0"));
    optTree.addEventListener("change", () => { store.set("cssc.optTree", optTree.checked ? "1" : "0"); applyTreeVisibility(); });
    $("projectTitle").addEventListener("click", () => { S.treeOpen = !($("optTree").checked || S.treeOpen); applyTreeVisibility(); });

    document.addEventListener("langchange", () => {
      renderVersions($("versionSearch").value);
      renderTree();
      if (S.isDemo) { S.name = t("project.demo"); $("projectName").textContent = "· " + S.name; }
      loadStats();
      updateInfo();
    });
    document.addEventListener("siteinfo", updateInfo);
  }

  function updateInfo() {
    const info = window.SITE_INFO || {};
    $("dropSub").textContent = t("settings.dropSub", { mb: info.max_upload_mb || 20 });
    $("limitInfo").textContent = info.rate_limit_per_hour ? t("settings.limit", { n: info.rate_limit_per_hour }) : "";
    $("privacyNote").textContent = t("footer.privacyNote", { min: info.job_ttl_min || 60 });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    updateInfo();
    if (!restoreProject()) {
      loadDemo();
    } else {
      afterProjectChange();
    }
    await loadVersions();
    loadStats();
  });
})();
