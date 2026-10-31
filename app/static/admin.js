/* Admin-Bereich */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const STATUS = { success: "Erfolgreich", failed: "Fehlgeschlagen", rejected: "Abgelehnt", mismatch: "Versionskonflikt", queued: "Wartet", restoring: "Pakete", building: "Baut" };

  function show(which) {
    $("loginBox").hidden = which !== "login";
    $("disabledBox").hidden = which !== "disabled";
    $("dash").hidden = which !== "dash";
    $("logoutBtn").hidden = which !== "dash";
  }

  const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–";

  async function load() {
    let r;
    try { r = await fetch(BASE + "/api/admin/overview", { cache: "no-store" }); } catch (e) { toast("Server nicht erreichbar"); return; }
    const d = await r.json();
    if (r.status === 401) { show(d.enabled === false ? "disabled" : "login"); return; }
    show("dash");
    render(d);
  }

  function render(d) {
    const s = d.stats;
    const kpi = (l, v) => `<div class="card kpi"><div class="l">${esc(l)}</div><div class="v">${v}</div></div>`;
    $("kpis").innerHTML =
      kpi("Erfolgreich", `<span style="color:var(--ok)">${s.total_success}</span>`) +
      kpi("Fehlgeschlagen", `<span style="color:var(--err)">${s.total_failed}</span>`) +
      kpi("Warteschlange", d.queue) +
      kpi("Läuft gerade", Object.keys(d.running).length) +
      kpi("NuGet-Cache", fmtSize(d.nuget_cache_bytes)) +
      kpi("Speicher frei", fmtSize(d.disk_free));

    $("jobsBody").innerHTML = d.jobs.map((j) => `
      <tr class="click" data-id="${esc(j.id)}">
        <td>${esc(fmtTime(j.created))}</td>
        <td><span class="badge ${esc(j.status)}">${esc(STATUS[j.status] || j.status)}</span></td>
        <td>${esc(j.project || "–")}</td>
        <td>${esc(j.api_version || "–")}</td>
        <td>${esc(j.framework || "–")}</td>
        <td>${esc(j.configuration || "–")}</td>
        <td>${j.duration != null ? esc(j.duration) + " s" : "–"}</td>
        <td class="mono small" title="Gehashte IP">${esc((j.ip_hash || "").slice(0, 8))}</td>
        <td class="sum">${esc(j.summary || "")}</td>
      </tr>`).join("") || `<tr><td colspan="9" class="muted">Noch keine Aufträge</td></tr>`;
    $("jobsBody").querySelectorAll("tr[data-id]").forEach((tr) => tr.addEventListener("click", () => openLog(tr.dataset.id)));

    const sb = d.sandbox;
    $("sandboxInfo").innerHTML = `
      <p>Docker: <b>${sb.docker ? "erreichbar" : "NICHT erreichbar"}</b><br>
      SDK-Image: <b>${esc(d.config.sdk_image)}</b> – ${esc({ ready: "bereit", pulling: "wird geladen", error: "Fehler", unknown: "unbekannt" }[sb.image] || sb.image)}</p>
      ${sb.error ? `<p class="box err mono">${esc(sb.error)}</p>` : ""}
      <p class="muted">Compiler-Version ${esc(d.version)}</p>`;

    $("topVersions").innerHTML = (s.versions || []).map((v) =>
      `<div class="bar-row" style="grid-template-columns:90px 1fr 70px"><span class="mono">${esc(v.version)}</span><div class="bar ok"><i style="width:${v.total ? Math.round(v.success / v.total * 100) : 0}%"></i></div><span class="n">${v.success}/${v.total}</span></div>`
    ).join("") || `<span class="muted">Noch keine Daten</span>`;

    const c = d.config;
    const rows = [
      ["Parallele Builds", c.max_parallel], ["Max. Warteschlange", c.max_queue], ["Limit pro Stunde/IP", c.rate_limit_per_hour],
      ["Max. Upload", c.max_upload_mb + " MB"], ["RAM pro Build", c.build_memory], ["CPUs pro Build", c.build_cpus],
      ["Zeitlimit Restore", c.restore_timeout + " s"], ["Zeitlimit Build", c.build_timeout + " s"],
      ["Ergebnisse behalten", c.job_ttl_min + " Min."], ["Verlauf behalten", c.history_days + " Tage"],
    ];
    $("cfgInfo").innerHTML = `<table class="list">${rows.map(([k, v]) => `<tr><td class="muted">${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>`;
  }

  async function openLog(id) {
    const r = await fetch(BASE + `/api/admin/jobs/${id}/log`);
    const d = await r.json();
    $("logTitle").textContent = "Log " + id.slice(0, 8);
    $("logBody").textContent = d.log || d.summary || "(kein Log – Auftrag wurde vor dem Build abgelehnt)";
    $("logModal").hidden = false;
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("loginForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      $("loginErr").hidden = true;
      const r = await fetch(BASE + "/api/admin/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("pw").value }) });
      if (r.ok) { $("pw").value = ""; load(); return; }
      const d = await r.json().catch(() => ({}));
      $("loginErr").textContent = { wrong_password: "Falsches Passwort.", too_many_attempts: "Zu viele Versuche – bitte 15 Minuten warten.", admin_disabled: "Admin-Bereich ist deaktiviert." }[d.error] || "Anmeldung fehlgeschlagen.";
      $("loginErr").hidden = false;
    });
    $("logoutBtn").addEventListener("click", async () => { await fetch(BASE + "/api/admin/logout", { method: "POST" }); show("login"); });
    $("reloadBtn").addEventListener("click", load);
    $("logClose").addEventListener("click", () => { $("logModal").hidden = true; });
    $("logModal").addEventListener("click", (e) => { if (e.target === $("logModal")) $("logModal").hidden = true; });
    document.querySelectorAll("[data-action]").forEach((b) => b.addEventListener("click", async () => {
      const a = b.dataset.action;
      if (a === "clear-nuget" && !confirm("NuGet-Cache wirklich leeren? Die nächsten Builds laden alle Pakete neu.")) return;
      b.disabled = true;
      try {
        const r = await fetch(BASE + "/api/admin/action/" + a, { method: "POST" });
        const d = await r.json();
        if (!r.ok) toast(d.error === "busy" ? "Gerade laufen Builds – bitte später." : "Fehler: " + d.error);
        else toast(a === "refresh-versions" ? `${d.count} Versionen geladen` : a === "cleanup" ? `${d.removed} Ordner gelöscht` : a === "pull-image" ? "Image wird im Hintergrund aktualisiert" : "Erledigt");
      } finally { b.disabled = false; load(); }
    }));
    load();
    setInterval(() => { if (!$("dash").hidden && $("logModal").hidden) load(); }, 20000);
  });
})();
