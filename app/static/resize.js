/* Editor-Größe anpassen: Höhe (unten ziehen), Dateiliste/Editor (seitlich ziehen),
   Einstellungen/Editor (Spaltengrenze ziehen), volle Breite – ab 1.3.1, Spaltengriff ab 1.3.2 */
(function () {
  "use strict";
  const MIN_H = 300, MAX_H = 2400, MIN_TREE = 120, MIN_EDITOR = 260;

  function refreshEditors(root) {
    root.querySelectorAll(".CodeMirror").forEach((el) => { if (el.CodeMirror) el.CodeMirror.refresh(); });
  }

  function drag(handle, axis, onMove, onEnd) {
    handle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      handle.classList.add("dragging");
      document.body.classList.add("resizing", "resizing-" + axis);
      const move = (ev) => onMove(ev);
      const up = () => {
        handle.classList.remove("dragging");
        document.body.classList.remove("resizing", "resizing-" + axis);
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        onEnd();
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);
    });
  }

  function setup(ex) {
    const key = "cssc.ed." + ex.id;
    const tree = ex.querySelector(":scope > .tree");
    const wrap = ex.querySelector(":scope > .editor-wrap");
    if (!tree || !wrap) return;

    // gespeicherte Größen
    const h = parseInt(store.get(key + ".h", ""), 10);
    const w = parseInt(store.get(key + ".w", ""), 10);
    if (h >= MIN_H) ex.style.setProperty("--ed-h", Math.min(h, MAX_H) + "px");
    if (w >= MIN_TREE) ex.style.setProperty("--tree-w", w + "px");

    // Griff zwischen Dateiliste und Editor
    const sx = document.createElement("div");
    sx.className = "split-x";
    sx.setAttribute("role", "separator");
    sx.setAttribute("aria-orientation", "vertical");
    sx.setAttribute("aria-label", t("ed.resizeTree"));
    sx.tabIndex = 0;
    ex.insertBefore(sx, wrap);

    // Griff unten für die Höhe
    const sy = document.createElement("div");
    sy.className = "split-y";
    sy.setAttribute("role", "separator");
    sy.setAttribute("aria-orientation", "horizontal");
    sy.setAttribute("aria-label", t("ed.resizeHeight"));
    sy.title = t("ed.resizeHeight");
    sy.tabIndex = 0;
    ex.appendChild(sy);

    const setTree = (px) => {
      const max = ex.clientWidth - MIN_EDITOR;
      px = Math.round(Math.max(MIN_TREE, Math.min(px, max)));
      ex.style.setProperty("--tree-w", px + "px");
      return px;
    };
    const setHeight = (px) => {
      px = Math.round(Math.max(MIN_H, Math.min(px, MAX_H)));
      ex.style.setProperty("--ed-h", px + "px");
      return px;
    };

    let raf = 0;
    const later = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => refreshEditors(ex)); };

    drag(sx, "x",
      (ev) => { setTree(ev.clientX - ex.getBoundingClientRect().left); later(); },
      () => { store.set(key + ".w", String(tree.getBoundingClientRect().width | 0)); refreshEditors(ex); });
    drag(sy, "y",
      (ev) => { setHeight(ev.clientY - ex.getBoundingClientRect().top); later(); },
      () => { store.set(key + ".h", String(ex.getBoundingClientRect().height | 0)); refreshEditors(ex); });

    // Tastatur: Pfeiltasten verschieben, Doppelklick setzt zurück
    sx.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const px = setTree(tree.getBoundingClientRect().width + (e.key === "ArrowLeft" ? -20 : 20));
      store.set(key + ".w", String(px)); refreshEditors(ex);
    });
    sy.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      e.preventDefault();
      const px = setHeight(ex.getBoundingClientRect().height + (e.key === "ArrowUp" ? -40 : 40));
      store.set(key + ".h", String(px)); refreshEditors(ex);
    });
    sx.addEventListener("dblclick", () => { ex.style.removeProperty("--tree-w"); store.set(key + ".w", ""); refreshEditors(ex); });
    sy.addEventListener("dblclick", () => { ex.style.removeProperty("--ed-h"); store.set(key + ".h", ""); refreshEditors(ex); });

    // Knopf "Breit": Editor über die ganze Seitenbreite
    const card = ex.closest(".card");
    const grid = ex.closest(".grid");
    const head = card && card.querySelector(".card-h");
    if (head && grid && grid.id) {
      const wkey = "cssc.wide." + grid.id;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-ghost btn-sm wide-btn";
      const apply = (on) => {
        grid.classList.toggle("wide", on);
        btn.setAttribute("aria-pressed", String(on));
        btn.textContent = on ? t("ed.narrow") : t("ed.wide");
        btn.title = on ? t("ed.narrowTitle") : t("ed.wideTitle");
        requestAnimationFrame(() => refreshEditors(ex));
      };
      btn.addEventListener("click", () => {
        const on = !grid.classList.contains("wide");
        store.set(wkey, on ? "1" : "");
        apply(on);
      });
      const spacer = head.querySelector(".spacer");
      if (spacer && spacer.nextSibling) head.insertBefore(btn, spacer.nextSibling);
      else head.appendChild(btn);
      apply(store.get(wkey, "") === "1");
      document.addEventListener("langchange", () => apply(grid.classList.contains("wide")));
    }
    document.addEventListener("langchange", () => {
      sx.setAttribute("aria-label", t("ed.resizeTree"));
      sy.setAttribute("aria-label", t("ed.resizeHeight"));
      sy.title = t("ed.resizeHeight");
    });
  }

  // Grenze zwischen Einstellungen (links) und Editor (rechts) verschieben
  const MIN_SIDE = 280, MIN_RIGHT = 420;
  function setupColumns(grid) {
    const key = "cssc.side." + grid.id;
    const saved = parseInt(store.get(key, ""), 10);
    if (saved >= MIN_SIDE) grid.style.setProperty("--side-w", saved + "px");
    const h = document.createElement("div");
    h.className = "split-col";
    h.setAttribute("role", "separator");
    h.setAttribute("aria-orientation", "vertical");
    h.setAttribute("aria-label", t("ed.resizeColumns"));
    h.title = t("ed.resizeColumns");
    h.tabIndex = 0;
    grid.appendChild(h);
    const side = () => grid.firstElementChild.getBoundingClientRect().width;
    const set = (px) => {
      const max = grid.clientWidth - MIN_RIGHT;
      px = Math.round(Math.max(MIN_SIDE, Math.min(px, max)));
      grid.style.setProperty("--side-w", px + "px");
      return px;
    };
    let raf = 0;
    drag(h, "x",
      (ev) => { set(ev.clientX - grid.getBoundingClientRect().left - 8); cancelAnimationFrame(raf); raf = requestAnimationFrame(() => refreshEditors(grid)); },
      () => { store.set(key, String(side() | 0)); refreshEditors(grid); });
    h.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      store.set(key, String(set(side() + (e.key === "ArrowLeft" ? -30 : 30)))); refreshEditors(grid);
    });
    h.addEventListener("dblclick", () => { grid.style.removeProperty("--side-w"); store.set(key, ""); refreshEditors(grid); });
    document.addEventListener("langchange", () => { h.setAttribute("aria-label", t("ed.resizeColumns")); h.title = t("ed.resizeColumns"); });
  }

  // Rechter Rand: ganze Seite breiter ziehen (über die normale Breite von 1240 px hinaus)
  const PAGE_MIN = 960, PAGE_DEFAULT = 1240;
  function setPage(px) {
    px = Math.round(Math.max(PAGE_MIN, Math.min(px, window.innerWidth)));
    document.documentElement.style.setProperty("--page-w", px + "px");
    return px;
  }
  function pageWidth() {
    const v = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--page-w"), 10);
    return v || PAGE_DEFAULT;
  }
  function setupPageEdge(grid) {
    const h = document.createElement("div");
    h.className = "split-page";
    h.setAttribute("role", "separator");
    h.setAttribute("aria-orientation", "vertical");
    h.setAttribute("aria-label", t("ed.resizePage"));
    h.title = t("ed.resizePage");
    h.tabIndex = 0;
    grid.appendChild(h);
    let raf = 0;
    const refreshAll = () => document.querySelectorAll(".explorer").forEach(refreshEditors);
    drag(h, "x",
      (ev) => {
        // Seite ist zentriert: Abstand zur Mitte x 2 + Innenabstand = neue Breite
        setPage(2 * (ev.clientX - window.innerWidth / 2) + 32);
        cancelAnimationFrame(raf); raf = requestAnimationFrame(refreshAll);
      },
      () => { store.set("cssc.pageW", String(pageWidth())); refreshAll(); });
    h.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      store.set("cssc.pageW", String(setPage(pageWidth() + (e.key === "ArrowLeft" ? -60 : 60)))); refreshAll();
    });
    h.addEventListener("dblclick", () => { document.documentElement.style.removeProperty("--page-w"); store.set("cssc.pageW", ""); refreshAll(); });
    document.addEventListener("langchange", () => { h.setAttribute("aria-label", t("ed.resizePage")); h.title = t("ed.resizePage"); });
  }

  // gespeicherte Seitenbreite sofort anwenden
  const pw = parseInt(store.get("cssc.pageW", ""), 10);
  if (pw >= PAGE_MIN) setPage(pw);

  document.addEventListener("DOMContentLoaded", () => {
    ["cssharpMode", "metamodMode"].forEach((id) => { const g = document.getElementById(id); if (g) { setupColumns(g); setupPageEdge(g); } });
    document.querySelectorAll(".explorer[id]").forEach(setup);
    window.addEventListener("resize", () => document.querySelectorAll(".explorer").forEach(refreshEditors));
  });
})();
