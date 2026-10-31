/* Gemeinsame Funktionen: Sprache, Design, Statusanzeige */
(function () {
  const bm = document.querySelector('meta[name="base-path"]');
  window.BASE = (bm && bm.content) || "";
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* egal */ } },
  };
  window.store = store;

  // ---- Sprache ----------------------------------------------------------
  let lang = store.get("cssc.lang", (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en");
  if (!window.I18N[lang]) lang = "de";
  window.getLang = () => lang;

  // Eigene Texte aus der .env (z. B. HERO_TITLE_DE) haben Vorrang
  let custom = {};
  try {
    const tm = document.querySelector('meta[name="site-texts"]');
    if (tm && tm.content) custom = JSON.parse(tm.content) || {};
  } catch (e) { custom = {}; }

  window.t = function (key, vars) {
    let s = (custom[lang] && custom[lang][key]) || (window.I18N[lang] && window.I18N[lang][key]) || (window.I18N.de[key]) || key;
    if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
    return s;
  };

  window.applyI18n = function (root) {
    (root || document).querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    (root || document).querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
    (root || document).querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-lang-block]").forEach((el) => { el.hidden = el.dataset.langBlock !== lang; });
    const lb = document.getElementById("langBtn");
    if (lb) lb.textContent = lang === "de" ? "EN" : "DE";
    const tb = document.getElementById("themeBtn");
    if (tb) tb.textContent = t("theme." + store.get("cssc.theme", "auto"));
  };

  window.setLang = function (l) {
    lang = l; store.set("cssc.lang", l); applyI18n();
    document.dispatchEvent(new CustomEvent("langchange"));
  };

  // ---- Design (Auto / Hell / Dunkel) -------------------------------------
  const themes = ["auto", "light", "dark"];
  function applyTheme(th) {
    if (th === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", th);
    const b = document.getElementById("themeBtn");
    if (b) b.textContent = t("theme." + th);
  }
  let theme = store.get("cssc.theme", "auto");
  applyTheme(theme);

  // ---- Helfer -------------------------------------------------------------
  window.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  window.fmtSize = (n) => {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
    return (n / 1073741824).toFixed(1) + " GB";
  };
  window.toast = (msg) => {
    const el = document.createElement("div");
    el.className = "toast"; el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  };
  window.tfLabel = (tf) => {
    const m = /^net(\d+\.\d+)$/.exec(tf || "");
    return m ? ".NET " + m[1] : (tf || "?");
  };

  // ---- Statusanzeige ------------------------------------------------------
  async function refreshStatus() {
    const box = document.getElementById("statusPills");
    if (!box) return;
    try {
      const r = await fetch(BASE + "/api/status", { cache: "no-store" });
      const s = await r.json();
      const sb = { running: ["ok", "status.running"], pulling: ["warn", "status.pulling"], down: ["err", "status.down"], error: ["err", "status.error"] }[s.sandbox] || ["warn", "status.unknown"];
      const ld = { low: "ok", medium: "warn", high: "err" }[s.load] || "warn";
      box.innerHTML =
        `<span class="pill"><span class="dot ${sb[0]}"></span>${esc(t("status.sandbox"))}: ${esc(t(sb[1]))}</span>` +
        `<span class="pill"><span class="dot ${ld}"></span>${esc(t("status.load"))}: ${esc(t("load." + s.load))}</span>` +
        `<span class="pill">${esc(t("status.queue"))}: ${s.queue}</span>`;
    } catch (e) {
      box.innerHTML = `<span class="pill"><span class="dot err"></span>${esc(t("status.sandbox"))}: ${esc(t("status.down"))}</span>`;
    }
  }
  window.refreshStatus = refreshStatus;

  document.addEventListener("DOMContentLoaded", () => {
    applyI18n();
    applyTheme(theme);
    const tb = document.getElementById("themeBtn");
    if (tb) tb.addEventListener("click", () => {
      theme = themes[(themes.indexOf(theme) + 1) % themes.length];
      store.set("cssc.theme", theme); applyTheme(theme);
      document.dispatchEvent(new CustomEvent("themechange"));
    });
    const lb = document.getElementById("langBtn");
    if (lb) lb.addEventListener("click", () => setLang(lang === "de" ? "en" : "de"));
    refreshStatus();
    setInterval(refreshStatus, 15000);
    document.addEventListener("langchange", refreshStatus);

    // Fußzeile: Impressum/Datenschutz aus der Konfiguration
    fetch(BASE + "/api/info").then((r) => r.json()).then((info) => {
      window.SITE_INFO = info;
      const imp = document.getElementById("lnkImpressum");
      const dse = document.getElementById("lnkPrivacy");
      if (imp && info.impressum_url) { imp.href = info.impressum_url; imp.hidden = false; }
      if (dse && info.datenschutz_url) { dse.href = info.datenschutz_url; dse.hidden = false; }
      document.dispatchEvent(new CustomEvent("siteinfo", { detail: info }));
    }).catch(() => {});
  });
})();
