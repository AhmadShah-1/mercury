"use strict";
/*
 * Mercury progressive enhancement. Every feature here has a working no-JS fallback:
 * links open the full-page reader, forms post normally, and the server renders all state.
 * Rules: no eval, no inline handlers, no HTML strings built from data (textContent only),
 * and nothing derived from mail is written to storage or URLs.
 */
(function () {
  const doc = document;
  const root = doc.documentElement;
  const wideReader = window.matchMedia("(min-width: 1100px)");

  const csrfToken = () => doc.querySelector('meta[name="csrf-token"]')?.content || "";
  const safeStorage = {
    get(store, key) {
      try { return window[store].getItem(key); } catch (error) { return null; }
    },
    set(store, key, value) {
      try { window[store].setItem(key, value); } catch (error) { /* storage unavailable */ }
    },
    remove(store, key) {
      try { window[store].removeItem(key); } catch (error) { /* storage unavailable */ }
    },
  };
  const isTyping = (el) => !!el?.closest?.('input, textarea, select, [contenteditable="true"]');
  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  /* ------------------------------------------------------------- CSRF */
  doc.addEventListener("htmx:configRequest", (event) => {
    const token = csrfToken();
    if (token) event.detail.headers["X-CSRFToken"] = token;
  });

  /* ------------------------------------------------------------ theme */
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const effectiveDark = () => {
    const chosen = root.getAttribute("data-theme");
    return chosen ? chosen === "dark" : systemDark.matches;
  };
  const syncTheme = () => {
    const dark = effectiveDark();
    root.setAttribute("data-bs-theme", dark ? "dark" : "light");
    doc.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", String(dark));
      button.title = dark ? "Switch to light theme" : "Switch to dark theme";
    });
  };
  doc.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    const next = effectiveDark() ? "light" : "dark";
    if (next === (systemDark.matches ? "dark" : "light")) {
      root.removeAttribute("data-theme");
      safeStorage.remove("localStorage", "mercury-theme");
    } else {
      root.setAttribute("data-theme", next);
      safeStorage.set("localStorage", "mercury-theme", next);
    }
    syncTheme();
  });
  systemDark.addEventListener?.("change", syncTheme);

  /* ----------------------------------------------------------- toasts */
  const toastStack = () => doc.getElementById("toast-stack");
  const dismissToast = (toast) => {
    if (!toast || toast.classList.contains("is-leaving")) return;
    toast.classList.add("is-leaving");
    const remove = () => toast.remove();
    toast.addEventListener("animationend", remove, { once: true });
    window.setTimeout(remove, 400);
  };
  const armToast = (toast) => {
    if (toast.dataset.armed) return;
    toast.dataset.armed = "1";
    if (!toast.hasAttribute("data-autodismiss")) return;
    let timer = window.setTimeout(() => dismissToast(toast), 6500);
    const pause = () => window.clearTimeout(timer);
    const resume = () => { timer = window.setTimeout(() => dismissToast(toast), 3000); };
    toast.addEventListener("mouseenter", pause);
    toast.addEventListener("focusin", pause);
    toast.addEventListener("mouseleave", resume);
    toast.addEventListener("focusout", resume);
  };
  const showToast = (message, tone = "success") => {
    const stack = toastStack();
    if (!stack) return;
    const toast = el("div", `toast-m toast-${tone}`);
    toast.setAttribute("role", tone === "danger" ? "alert" : "status");
    toast.setAttribute("data-toast", "");
    if (tone === "success" || tone === "info") toast.setAttribute("data-autodismiss", "");
    toast.append(el("p", "toast-text", message));
    const close = el("button", "toast-close", "×");
    close.type = "button";
    close.setAttribute("data-toast-close", "");
    close.setAttribute("aria-label", "Dismiss notification");
    toast.append(close);
    stack.append(toast);
    armToast(toast);
  };
  doc.addEventListener("click", (event) => {
    const close = event.target.closest("[data-toast-close]");
    if (close) dismissToast(close.closest("[data-toast]"));
  });
  const watchToasts = () => {
    const stack = toastStack();
    if (!stack) return;
    stack.querySelectorAll("[data-toast]").forEach(armToast);
    new MutationObserver(() => stack.querySelectorAll("[data-toast]").forEach(armToast)).observe(stack, { childList: true });
    const pending = safeStorage.get("sessionStorage", "mercury-notice");
    if (pending) {
      safeStorage.remove("sessionStorage", "mercury-notice");
      const moved = /^moved:(\d{1,3})$/.exec(pending);
      if (moved) showToast(`Moved ${moved[1]} ${moved[1] === "1" ? "conversation" : "conversations"}. Mercury will keep them there.`);
    }
  };

  /* ------------------------------------------------------ local times */
  const fmt = (options) => {
    try { return new Intl.DateTimeFormat(undefined, options); } catch (error) { return null; }
  };
  const fmtTime = fmt({ hour: "numeric", minute: "2-digit" });
  const fmtDay = fmt({ month: "short", day: "numeric" });
  const fmtDate = fmt({ month: "short", day: "numeric", year: "numeric" });
  const fmtLong = fmt({ weekday: "short", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  const fmtSeconds = fmt({ hour: "numeric", minute: "2-digit", second: "2-digit" });
  const relative = (() => { try { return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }); } catch (error) { return null; } })();
  const localizeTimes = (scope) => {
    if (!fmtTime) return;
    (scope || doc).querySelectorAll("time[data-localtime]").forEach((node) => {
      const date = new Date(node.getAttribute("datetime"));
      if (Number.isNaN(date.getTime())) return;
      const now = new Date();
      const mode = node.dataset.localtime;
      let text;
      if (mode === "long") text = fmtLong.format(date);
      else if (mode === "time") text = fmtSeconds.format(date);
      else if (mode === "relative" && relative) {
        const minutes = Math.round((date - now) / 60000);
        if (Math.abs(minutes) < 1) text = "just now";
        else if (Math.abs(minutes) < 60) text = relative.format(minutes, "minute");
        else if (Math.abs(minutes) < 60 * 24) text = relative.format(Math.round(minutes / 60), "hour");
        else text = relative.format(Math.round(minutes / 1440), "day");
      } else if (date.toDateString() === now.toDateString()) text = fmtTime.format(date);
      else if (date.getFullYear() === now.getFullYear()) text = fmtDay.format(date);
      else text = fmtDate.format(date);
      node.textContent = text;
      node.title = fmtLong.format(date);
    });
  };

  /* ---------------------------------------------------- confirmations */
  const confirmDialog = () => doc.getElementById("confirm-dialog");
  doc.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-confirm")) return;
    if (form.dataset.confirmed === "1") return;
    const dialog = confirmDialog();
    if (!dialog || typeof dialog.showModal !== "function") return;
    event.preventDefault();
    const submitter = event.submitter;
    dialog.querySelector("#confirm-title").textContent = form.dataset.confirmTitle || "Please confirm";
    dialog.querySelector("#confirm-message").textContent = form.getAttribute("data-confirm");
    const accept = dialog.querySelector("[data-confirm-accept]");
    accept.textContent = form.dataset.confirmLabel || "Continue";
    dialog.returnValue = "";
    dialog.addEventListener("close", function onClose() {
      if (dialog.returnValue === "confirm") {
        form.dataset.confirmed = "1";
        if (submitter && typeof form.requestSubmit === "function") form.requestSubmit(submitter);
        else form.submit();
      }
    }, { once: true });
    dialog.showModal();
    dialog.querySelector("button[value='cancel']")?.focus();
  });

  /* Busy labels for long-ish plain form posts (e.g. Sync now). */
  doc.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    const button = event.target.querySelector?.("[data-busy-label]");
    if (!button) return;
    window.setTimeout(() => {
      button.disabled = true;
      button.textContent = button.dataset.busyLabel;
    }, 0);
  });

  /* ------------------------------------------------ workspace: reader */
  const readerPanel = () => doc.querySelector("[data-reader-panel]:not([data-reader-standalone])");
  const threadRows = () => Array.from(doc.querySelectorAll("[data-thread-list] [data-thread-row]"));
  const visibleRows = () => threadRows().filter((row) => !row.classList.contains("is-hidden"));
  let lastReaderRowId = null;

  const markCurrent = (rowId) => {
    lastReaderRowId = rowId;
    threadRows().forEach((row) => {
      const current = row.id === rowId;
      row.classList.toggle("is-current", current);
      const link = row.querySelector("[data-reader-link]");
      if (current) link?.setAttribute("aria-current", "true");
      else link?.removeAttribute("aria-current");
    });
  };

  const openInPanel = (link) => {
    const panel = readerPanel();
    if (!panel || !window.htmx || !wideReader.matches) return false;
    const row = link.closest("[data-thread-row]");
    markCurrent(row?.id || null);
    const skeleton = doc.getElementById("reader-skeleton");
    if (skeleton) panel.replaceChildren(skeleton.content.cloneNode(true));
    panel.classList.add("is-loading");
    panel.scrollTop = 0;
    window.htmx.ajax("GET", link.getAttribute("href"), { target: panel, swap: "innerHTML" });
    return true;
  };

  doc.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-reader-link]");
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (openInPanel(link)) event.preventDefault();
  });

  const renderPanelError = (panel, href) => {
    const box = el("div", "reader-empty");
    box.append(el("h2", "reader-empty-title", "This conversation couldn't be loaded"));
    box.append(el("p", "", "Mercury's saved organization is unchanged. Try again, or open the full reader page."));
    if (href) {
      const link = el("a", "btn btn-quiet btn-sm", "Open full reader");
      link.href = href;
      box.append(link);
    }
    panel.replaceChildren(box);
  };
  const renderBodyError = (target) => {
    const wrap = el("div", "state state-warning");
    wrap.setAttribute("role", "status");
    const body = el("div", "state-body");
    body.append(el("p", "state-title", "Original text couldn't be loaded"));
    body.append(el("p", "", "Gmail didn't respond in time. The summary above is still Mercury's saved analysis, not the original. Use Open in Gmail, or try again."));
    const retry = el("button", "btn btn-sm btn-quiet", "Try again");
    retry.type = "button";
    retry.addEventListener("click", () => {
      target.replaceChildren(el("p", "loading-text", "Fetching original message text from Gmail…"));
      window.htmx?.ajax("GET", target.getAttribute("hx-get"), { target, swap: "innerHTML" });
    });
    body.append(retry);
    wrap.append(el("span", "state-icon"), body);
    target.replaceChildren(wrap);
    target.removeAttribute("aria-busy");
  };

  // Server-rendered 404/409/503 states for the message body are meant to be shown.
  doc.addEventListener("htmx:beforeSwap", (event) => {
    const { xhr, target } = event.detail;
    if (!xhr || xhr.status < 400) return;
    if (target?.hasAttribute("data-swap-errors") && [404, 409, 503].includes(xhr.status)) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });
  const onFailure = (event) => {
    const target = event.detail?.target;
    const panel = readerPanel();
    if (!target) return;
    if (target.id === "message-body") {
      if (event.type === "htmx:responseError" && [404, 409, 503].includes(event.detail.xhr?.status)) return;
      renderBodyError(target);
    } else if (panel && target === panel) {
      panel.classList.remove("is-loading");
      if ([400, 409].includes(event.detail.xhr?.status)) {
        showToast("That change couldn't be saved. Reload the page and try again.", "danger");
      }
      const current = lastReaderRowId && doc.getElementById(lastReaderRowId)?.querySelector("[data-reader-link]");
      renderPanelError(panel, current?.getAttribute("href"));
    } else if (target.closest("[data-reader-panel]")) {
      showToast("That change couldn't be saved. Reload the page and try again.", "danger");
    }
  };
  ["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach((name) => doc.addEventListener(name, onFailure));

  doc.addEventListener("htmx:afterSwap", (event) => {
    const target = event.detail.target;
    if (!target) return;
    if (target.id === "message-body") target.removeAttribute("aria-busy");
    if (target.matches("[data-reader-panel]")) {
      target.classList.remove("is-loading");
      const heading = target.querySelector("#reader-subject");
      if (!target.hasAttribute("data-reader-standalone")) target.scrollTop = 0;
      heading?.focus({ preventScroll: true });
      const reader = target.querySelector("[data-reader]");
      if (reader && !target.hasAttribute("data-reader-standalone")) markCurrent(`thread-${reader.dataset.threadId}`);
    }
  });
  doc.addEventListener("htmx:afterSettle", (event) => {
    // A newly appended page of rows joins the active filter and the shown count.
    if (event.detail.target?.closest?.("[data-thread-list]")) applyFilter();
    syncSelection();
  });

  /* ---------------------------------------------- workspace: selection */
  const selected = new Set();
  const bulkBar = () => doc.querySelector("[data-bulk-bar]");
  const syncSelection = () => {
    const rows = threadRows();
    const present = new Set(rows.map((row) => row.querySelector("[data-row-select]")?.value));
    Array.from(selected).forEach((id) => { if (!present.has(id)) selected.delete(id); });
    rows.forEach((row) => {
      const box = row.querySelector("[data-row-select]");
      if (!box) return;
      box.checked = selected.has(box.value);
      row.classList.toggle("is-selected", box.checked);
    });
    const bar = bulkBar();
    if (bar) {
      bar.hidden = selected.size === 0;
      const counter = bar.querySelector("[data-bulk-count]");
      if (counter) counter.textContent = `${selected.size} selected`;
    }
    const all = doc.querySelector("[data-select-all]");
    if (all) {
      const visible = visibleRows();
      const chosen = visible.filter((row) => selected.has(row.querySelector("[data-row-select]")?.value)).length;
      all.checked = visible.length > 0 && chosen === visible.length;
      all.indeterminate = chosen > 0 && chosen < visible.length;
    }
  };
  doc.addEventListener("change", (event) => {
    const box = event.target.closest?.("[data-row-select]");
    if (box) {
      if (box.checked) selected.add(box.value);
      else selected.delete(box.value);
      syncSelection();
      return;
    }
    const all = event.target.closest?.("[data-select-all]");
    if (all) {
      visibleRows().forEach((row) => {
        const value = row.querySelector("[data-row-select]")?.value;
        if (!value) return;
        if (all.checked) selected.add(value);
        else selected.delete(value);
      });
      syncSelection();
    }
  });
  doc.addEventListener("click", (event) => {
    if (event.target.closest("[data-bulk-clear]")) {
      selected.clear();
      syncSelection();
    }
  });

  /* Bulk move: sequential POSTs to the existing per-thread move endpoint (CSRF + ownership
     are enforced server-side for each one). Selection lives only in memory. */
  const bulkDialog = () => doc.getElementById("bulk-move-dialog");
  const openBulkMove = () => {
    const dialog = bulkDialog();
    if (!dialog || selected.size === 0 || typeof dialog.showModal !== "function") return;
    const count = selected.size;
    const noun = `${count} ${count === 1 ? "conversation" : "conversations"}`;
    dialog.querySelector("[data-bulk-noun]").textContent = noun;
    dialog.querySelector("[data-bulk-number]").textContent = String(count);
    const status = dialog.querySelector("[data-bulk-status]");
    status.textContent = "";
    status.classList.remove("is-error");
    dialog.querySelector("[data-bulk-confirm]").disabled = false;
    dialog.showModal();
    dialog.querySelector("[data-bulk-destination]")?.focus();
  };
  doc.addEventListener("click", (event) => {
    if (event.target.closest("[data-bulk-move]")) openBulkMove();
  });
  doc.addEventListener("click", async (event) => {
    const confirm = event.target.closest("[data-bulk-confirm]");
    if (!confirm) return;
    const dialog = bulkDialog();
    const destination = dialog.querySelector("[data-bulk-destination]").value;
    const status = dialog.querySelector("[data-bulk-status]");
    const rows = threadRows().filter((row) => selected.has(row.querySelector("[data-row-select]")?.value));
    if (!destination || rows.length === 0) return;
    confirm.disabled = true;
    const token = csrfToken();
    let moved = 0;
    let failed = 0;
    for (const row of rows) {
      status.textContent = `Moving ${moved + failed + 1} of ${rows.length}…`;
      try {
        const response = await fetch(row.dataset.moveUrl, {
          method: "POST",
          credentials: "same-origin",
          redirect: "manual",
          headers: { "X-CSRFToken": token, "X-Mercury-Bulk": "1" },
          body: new URLSearchParams({ csrf_token: token, bucket_id: destination }),
        });
        if (response.type === "opaqueredirect" || response.ok) moved += 1;
        else failed += 1;
      } catch (error) {
        failed += 1;
      }
    }
    if (failed) {
      status.classList.add("is-error");
      status.textContent = `${moved} moved, ${failed} couldn't be moved. Reload to see the current state.`;
      confirm.disabled = false;
      return;
    }
    safeStorage.set("sessionStorage", "mercury-notice", `moved:${moved}`);
    dialog.close();
    window.location.reload();
  });

  /* ---------------------------------------------- workspace: filtering */
  const applyFilter = () => {
    const input = doc.querySelector("[data-list-filter]");
    if (!input) return;
    const query = input.value.trim().toLocaleLowerCase();
    let shown = 0;
    threadRows().forEach((row) => {
      const match = !query || row.querySelector("[data-reader-link]").textContent.toLocaleLowerCase().includes(query);
      row.classList.toggle("is-hidden", !match);
      if (match) shown += 1;
    });
    const counter = doc.querySelector("[data-list-count]");
    if (counter) counter.textContent = String(shown);
    const empty = doc.querySelector("[data-filter-empty]");
    if (empty) empty.hidden = shown !== 0;
    syncSelection();
  };
  doc.addEventListener("input", (event) => {
    if (event.target.matches?.("[data-list-filter]")) applyFilter();
  });

  /* ------------------------------------------------ keyboard shortcuts */
  const shortcutsDialog = () => doc.getElementById("shortcuts-dialog");
  const focusedRow = () => doc.activeElement?.closest?.("[data-thread-row]") || (lastReaderRowId && doc.getElementById(lastReaderRowId));
  const moveFocus = (delta) => {
    const rows = visibleRows();
    if (!rows.length) return;
    const current = focusedRow();
    let index = current ? rows.indexOf(current) : -1;
    index = index === -1 ? (delta > 0 ? 0 : rows.length - 1) : Math.min(rows.length - 1, Math.max(0, index + delta));
    const link = rows[index].querySelector("[data-reader-link]");
    link.focus();
    link.scrollIntoView({ block: "nearest" });
  };
  doc.addEventListener("click", (event) => {
    if (!event.target.closest("[data-shortcuts-open]")) return;
    shortcutsDialog()?.showModal?.();
  });
  doc.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    if (doc.querySelector("dialog[open]")) return;
    const list = doc.querySelector("[data-thread-list]");
    const filter = doc.querySelector("[data-list-filter]");
    const target = event.target;
    if (isTyping(target)) {
      if (event.key === "Escape" && target === filter) {
        filter.value = "";
        applyFilter();
        moveFocus(0);
      } else if (event.key === "ArrowDown" && target === filter) {
        event.preventDefault();
        moveFocus(1);
      }
      return;
    }
    if (!list && event.key !== "?") return;
    const inList = !!target.closest?.("[data-thread-list]");
    switch (event.key) {
      case "?":
        if (shortcutsDialog()) { event.preventDefault(); shortcutsDialog().showModal(); }
        break;
      case "/":
        if (filter) { event.preventDefault(); filter.focus(); filter.select(); }
        break;
      case "j":
        event.preventDefault(); moveFocus(1); break;
      case "k":
        event.preventDefault(); moveFocus(-1); break;
      case "ArrowDown":
        if (inList) { event.preventDefault(); moveFocus(1); }
        break;
      case "ArrowUp":
        if (inList) { event.preventDefault(); moveFocus(-1); }
        break;
      case "o": {
        const row = focusedRow();
        row?.querySelector("[data-reader-link]")?.click();
        break;
      }
      case "x": {
        const row = focusedRow();
        const box = row?.querySelector("[data-row-select]");
        if (box) { event.preventDefault(); box.click(); }
        break;
      }
      case "m":
        if (selected.size) { event.preventDefault(); openBulkMove(); }
        break;
      case "Escape": {
        if (target.closest?.("[data-reader-panel]")) {
          const row = lastReaderRowId && doc.getElementById(lastReaderRowId);
          const link = row?.querySelector("[data-reader-link]");
          if (link) { event.preventDefault(); link.focus(); link.scrollIntoView({ block: "nearest" }); }
        } else if (selected.size) {
          selected.clear();
          syncSelection();
        }
        break;
      }
      default:
        break;
    }
  });

  /* ------------------------------------------------------------- init */
  const init = () => {
    syncTheme();
    watchToasts();
    localizeTimes(doc);
    syncSelection();
    const current = doc.querySelector("[data-thread-row].is-current");
    if (current) lastReaderRowId = current.id;
    if (window.htmx) window.htmx.onLoad((node) => localizeTimes(node.nodeType === 1 ? node : doc));
  };
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", init);
  else init();
})();
