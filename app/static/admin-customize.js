/* Admin: Reiter, Design- und Textverwaltung (ab 1.1.0) */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const HEX = /^#[0-9a-fA-F]{6}$/;

  let meta = null;      // { defaults, variables, env_site }
  let saved = null;     // zuletzt gespeicherter Stand
  let draft = null;     // aktueller Bearbeitungsstand
  let loaded = false;
  let tab = "overview";

  const clone = (o) => JSON.parse(JSON.stringify(o));
  const isDirty = () => saved && JSON.stringify(saved) !== JSON.stringify(draft);

  // ---- Reiter ----------------------------------------------------------------
  function showTab(name) {
    tab = name;
    document.querySelectorAll(".tab[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    document.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== name; });
    $("czBar").hidden = name === "overview";
    $("czTools").hidden = name === "overview";
    if (name !== "overview" && !loaded) load();
    try { history.replaceState(null, "", name === "overview" ? location.pathname + location.search : "#" + name); } catch (e) { /* egal */ }
  }

  // ---- Laden / Speichern -------------------------------------------------------
  async function load() {
    let r;
    try { r = await fetch(BASE + "/api/admin/customize", { cache: "no-store" }); } catch (e) { toast("Server nicht erreichbar"); return; }
    if (r.status === 401) { location.reload(); return; }
    const d = await r.json();
    meta = d; saved = clone(d.data); draft = clone(d.data); loaded = true;
    renderAll();
  }

  async function save(payload, msg) {
    const btn = $("czSave");
    btn.disabled = true;
    try {
      const r = await fetch(BASE + "/api/admin/customize", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const d = await r.json().catch(() => ({}));
      if (r.status === 401) { toast("Sitzung abgelaufen – bitte neu anmelden"); location.reload(); return; }
      if (!r.ok) {
        const why = {
          bad_value: "Ungültiger Wert bei " + (d.detail || "einer Variable") + " (keine ; { } < > erlaubt)",
          css_too_big: "Eigenes CSS ist zu groß",
          bad_format: "Ungültiges Format",
        }[d.error] || "Fehler: " + d.error;
        toast(why); return;
      }
      saved = clone(d.data); draft = clone(d.data);
      const link = $("customCss");
      if (link) link.href = BASE + "/custom.css?v=" + d.css_version;
      renderAll();
      toast(msg || "Gespeichert");
    } finally { btn.disabled = false; }
  }

  function markDirty() {
    const dirty = isDirty();
    $("czBar").classList.toggle("dirty", dirty);
    $("czState").textContent = dirty ? "Ungespeicherte Änderungen" : "Keine Änderungen";
  }

  // ---- Darstellung -------------------------------------------------------------
  function renderAll() {
    renderSite();
    $("czCss").value = draft.css || "";
    renderVars();
    renderTexts();
    markDirty();
  }

  function renderSite() {
    [["czName", "name"], ["czSubtitle", "subtitle"], ["czLogo", "logo"]].forEach(([id, key]) => {
      const el = $(id);
      el.value = draft.site[key] || "";
      el.placeholder = meta.env_site[key] || "";
    });
  }

  function varInput(v, theme) {
    const def = meta.defaults[theme][v.name] || "";
    const cur = (draft.vars[theme] || {})[v.name] || "";
    const pickVal = HEX.test(cur) ? cur : (HEX.test(def) ? def : "#000000");
    const picker = v.kind === "color"
      ? `<input type="color" value="${esc(pickVal)}" data-pick="${esc(v.name)}" data-theme="${theme}" aria-label="${esc(v.label)} (${theme === "light" ? "Hell" : "Dunkel"}) wählen">`
      : "";
    return `<div class="cz-in${cur ? " cz-changed" : ""}">${picker}
      <input type="text" value="${esc(cur)}" placeholder="${esc(def)}" data-var="${esc(v.name)}" data-theme="${theme}" aria-label="${esc(v.label)} (${theme === "light" ? "Hell" : "Dunkel"})" spellcheck="false">
      <button type="button" class="cz-x" data-clear="${esc(v.name)}" data-theme="${theme}" title="Standard wiederherstellen" aria-label="${esc(v.label)} zurücksetzen">×</button>
    </div>`;
  }

  function renderVars() {
    const onlyChanged = $("czVarsChanged").checked;
    let group = "", html = "";
    meta.variables.forEach((v) => {
      const changed = draft.vars.light[v.name] || draft.vars.dark[v.name];
      if (onlyChanged && !changed) return;
      if (v.group !== group) { group = v.group; html += `<tr class="grp"><td colspan="3">${esc(group)}</td></tr>`; }
      html += `<tr>
        <td class="cz-var-name">${esc(v.label)}<small>--${esc(v.name)}</small></td>
        <td${v.theme ? "" : ' colspan="2"'}>${varInput(v, "light")}</td>
        ${v.theme ? `<td>${varInput(v, "dark")}</td>` : ""}
      </tr>`;
    });
    $("czVarsBody").innerHTML = html || `<tr><td colspan="3" class="muted">Noch nichts geändert</td></tr>`;
  }

  function renderTexts() {
    const lang = $("czLang").value;
    const q = $("czSearch").value.trim().toLowerCase();
    const onlyChanged = $("czTextsChanged").checked;
    const base = window.I18N[lang] || {};
    const custom = draft.texts[lang] || {};
    const keys = Object.keys(window.I18N.de);
    const rows = [];
    for (const key of keys) {
      const def = base[key] != null ? base[key] : window.I18N.de[key];
      const cur = custom[key] || "";
      if (onlyChanged && !cur) continue;
      if (q && !(key.toLowerCase().includes(q) || String(def).toLowerCase().includes(q) || cur.toLowerCase().includes(q))) continue;
      const rowsN = Math.min(6, Math.max(1, Math.ceil(String(def).length / 70)));
      rows.push(`<tr class="${cur ? "cz-changed" : ""}">
        <td>${esc(key)}</td>
        <td><textarea rows="${rowsN}" data-text="${esc(key)}" placeholder="${esc(def)}" aria-label="Text für ${esc(key)}">${esc(cur)}</textarea></td>
      </tr>`);
      if (rows.length >= 400) break;
    }
    $("czTextsBody").innerHTML = rows.join("") || `<tr><td colspan="2" class="muted">Keine Treffer</td></tr>`;
  }

  // ---- Eingaben ----------------------------------------------------------------
  function setVar(name, theme, value) {
    value = value.trim();
    if (value) draft.vars[theme][name] = value; else delete draft.vars[theme][name];
  }

  function bind() {
    document.querySelectorAll(".tab[data-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

    [["czName", "name"], ["czSubtitle", "subtitle"], ["czLogo", "logo"]].forEach(([id, key]) => {
      $(id).addEventListener("input", (e) => { draft.site[key] = e.target.value; markDirty(); });
    });
    $("czCss").addEventListener("input", (e) => { draft.css = e.target.value; markDirty(); });
    $("czCss").addEventListener("keydown", (e) => {
      if (e.key !== "Tab" || e.shiftKey) return;
      e.preventDefault();
      const el = e.target, s = el.selectionStart;
      el.setRangeText("  ", s, el.selectionEnd, "end");
      draft.css = el.value; markDirty();
    });

    const vb = $("czVarsBody");
    vb.addEventListener("input", (e) => {
      const el = e.target;
      if (el.dataset.var) {
        setVar(el.dataset.var, el.dataset.theme, el.value);
        el.closest(".cz-in").classList.toggle("cz-changed", !!el.value.trim());
        const pick = el.parentElement.querySelector("input[type=color]");
        if (pick && HEX.test(el.value.trim())) pick.value = el.value.trim();
      } else if (el.dataset.pick) {
        const txt = el.parentElement.querySelector("input[type=text]");
        txt.value = el.value;
        setVar(el.dataset.pick, el.dataset.theme, el.value);
        el.closest(".cz-in").classList.add("cz-changed");
      }
      markDirty();
    });
    vb.addEventListener("click", (e) => {
      const b = e.target.closest("[data-clear]");
      if (!b) return;
      setVar(b.dataset.clear, b.dataset.theme, "");
      const box = b.closest(".cz-in");
      box.querySelector("input[type=text]").value = "";
      box.classList.remove("cz-changed");
      const pick = box.querySelector("input[type=color]");
      const def = meta.defaults[b.dataset.theme][b.dataset.clear];
      if (pick && HEX.test(def)) pick.value = def;
      markDirty();
    });
    $("czVarsChanged").addEventListener("change", renderVars);

    $("czTextsBody").addEventListener("input", (e) => {
      const el = e.target;
      if (!el.dataset.text) return;
      const lang = $("czLang").value;
      if (el.value.trim()) draft.texts[lang][el.dataset.text] = el.value; else delete draft.texts[lang][el.dataset.text];
      el.closest("tr").classList.toggle("cz-changed", !!el.value.trim());
      markDirty();
    });
    let st;
    $("czSearch").addEventListener("input", () => { clearTimeout(st); st = setTimeout(renderTexts, 150); });
    $("czLang").addEventListener("change", renderTexts);
    $("czTextsChanged").addEventListener("change", renderTexts);

    $("czSave").addEventListener("click", () => save(draft));
    $("czDiscard").addEventListener("click", () => {
      if (!isDirty() || confirm("Alle ungespeicherten Änderungen verwerfen?")) { draft = clone(saved); renderAll(); }
    });
    $("czReset").addEventListener("click", () => {
      const what = tab === "texts" ? "alle eigenen Texte" : "das komplette eigene Design (Seite, Variablen, CSS)";
      if (!confirm(`Wirklich ${what} auf Standard zurücksetzen? Danach wird sofort gespeichert.`)) return;
      const next = clone(saved);
      if (tab === "texts") next.texts = { de: {}, en: {} };
      else { next.site = { name: "", subtitle: "", logo: "" }; next.vars = { light: {}, dark: {} }; next.css = ""; }
      save(next, "Zurückgesetzt");
    });
    $("czExport").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(saved, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      const d = new Date();
      a.href = URL.createObjectURL(blob);
      a.download = `compiler-design_${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}.json`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
    $("czImport").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      e.target.value = "";
      if (!f) return;
      let data;
      try { data = JSON.parse(await f.text()); } catch (err) { toast("Datei ist keine gültige Sicherung"); return; }
      if (!confirm("Sicherung einspielen? Das aktuelle Design und alle eigenen Texte werden ersetzt.")) return;
      save(data, "Sicherung eingespielt");
    });

    window.addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bind();
    const start = (location.hash || "").slice(1);
    if (["design", "texts"].includes(start)) {
      // erst zeigen, wenn die Anmeldung geklappt hat
      const obs = new MutationObserver(() => { if (!$("dash").hidden) { obs.disconnect(); showTab(start); } });
      obs.observe($("dash"), { attributes: true, attributeFilter: ["hidden"] });
    }
  });
})();
