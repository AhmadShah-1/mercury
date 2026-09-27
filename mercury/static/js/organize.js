"use strict";
/*
 * Mercury crates: drag and drop, plus in-place posts for crate and bucket forms.
 * Progressive enhancement only: every action here is also an ordinary POST form (menus on
 * tiles, headers, and the edit page), so nothing depends on this file.
 * Rules (same as mercury.js): no eval, no innerHTML/insertAdjacentHTML, text via textContent
 * only, nothing from mail or bucket names goes to storage or URLs (session notices are fixed
 * codes), and dataTransfer carries only a kind plus UUIDs. The server stays the source of
 * truth: after each change the affected regions are re-fetched and swapped with htmx.
 */
(function () {
  const doc = document;
  const MIME = "application/x-mercury";
  const BOARD = "[data-org-board]";
  const NAV = "[data-ws-nav]";
  const HEAD = "[data-list-head]";
  const LIST = "[data-list-region]";
  const FOCUSABLE = "a[href], button:not([disabled]), summary, input:not([type=hidden]), select, textarea";
  const metaToken = () => doc.querySelector('meta[name="csrf-token"]')?.content || "";
  const toast = (message, tone = "success", action = null) => window.MercuryUI?.showToast?.(message, tone, action);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const isElement = (node) => node && node.nodeType === 1;
  const notice = (code) => {
    try { window.sessionStorage.setItem("mercury-notice", code); } catch (error) { /* storage unavailable */ }
  };
  const reload = (code) => {
    if (code) notice(code);
    window.location.reload();
  };
  const homeUrl = () => doc.querySelector("[data-home-url]")?.dataset.homeUrl || "/app";
  const onBoard = () => !!doc.querySelector(BOARD);
  const onScreenCrate = () => doc.querySelector(".crate-chips[data-crate-id]")?.dataset.crateId || "";

  /* ------------------------------------------------------ server calls */
  // Quiet requests answer 204, so only a 2xx is a success: a redirect (e.g. to sign-in after
  // the session expired) is a failure. `token` prefers a form's own CSRF field.
  const post = async (url, fields, { headers = {}, token = "" } = {}) => {
    const csrf = token || metaToken();
    const body = new URLSearchParams(fields);
    body.set("csrf_token", csrf);
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      redirect: "manual",
      headers: { "X-CSRFToken": csrf, "X-Mercury-Quiet": "1", ...headers },
      body,
    });
    if (response.ok) return response;
    const error = new Error("request failed");
    error.status = response.type === "opaqueredirect" ? 302 : response.status;
    throw error;
  };

  // Mutations run one at a time so a quick second drop never races the first refresh.
  let chain = Promise.resolve();
  const enqueue = (task) => {
    chain = chain.then(task).catch(() => {});
    return chain;
  };

  const focusKeyOf = (node) => node?.closest?.("[data-focus-key]")?.dataset.focusKey || null;
  const regionState = (focusKey) => {
    const active = doc.activeElement;
    return {
      focusKey: focusKey || focusKeyOf(active),
      focusInRegion: !!focusKey || !!active?.closest?.([BOARD, NAV, LIST].join(",")),
      scroll: [NAV, LIST].map((sel) => [sel, doc.querySelector(sel)?.scrollTop || 0]),
      filter: doc.querySelector("[data-list-filter]")?.value || "",
      currentRow: doc.querySelector("[data-thread-row].is-current")?.id || null,
    };
  };
  const focusByKey = (key) => {
    if (!key) return false;
    const node = doc.querySelector(`[data-focus-key="${CSS.escape(key)}"]`);
    const target = node && (node.matches(FOCUSABLE) ? node : node.querySelector(FOCUSABLE));
    if (!target) return false;
    target.focus({ preventScroll: true });
    return true;
  };
  const restoreState = (state) => {
    state.scroll.forEach(([sel, top]) => {
      const node = doc.querySelector(sel);
      if (node) node.scrollTop = top;
    });
    // Re-apply the filter and recount: a swapped header shows the first page's count.
    const filter = doc.querySelector("[data-list-filter]");
    if (filter) {
      filter.value = state.filter;
      filter.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (state.currentRow) {
      const row = doc.getElementById(state.currentRow);
      row?.classList.add("is-current");
      row?.querySelector("[data-reader-link]")?.setAttribute("aria-current", "true");
    }
    if (state.focusInRegion && !focusByKey(state.focusKey)) {
      (doc.getElementById("org-title") || doc.getElementById("main"))?.focus({ preventScroll: true });
    }
  };

  /* Which regions a change can affect. The list itself is re-fetched only when its rows can
     change, because a fresh GET holds just the first page (loaded older pages would vanish). */
  const scope = (listChanges = false) => (onBoard() ? [BOARD] : [NAV, listChanges ? LIST : HEAD]);

  /* Re-render regions from a fresh GET of this same page. The swap happens only when that GET
     is a plain 200 for this path and contains every region; otherwise the page reloads, since
     swapping with a missing selector would empty the region. */
  const refresh = async (wanted, focusKey = null) => {
    const selectors = wanted.filter((sel) => doc.querySelector(sel));
    if (!selectors.length) return;
    if (!window.htmx || typeof window.htmx.swap !== "function" || typeof DOMParser !== "function") {
      reload();
      return;
    }
    const response = await fetch(window.location.href, { credentials: "same-origin", headers: { Accept: "text/html" } });
    if (response.status === 404 && !response.redirected) {
      window.location.assign(homeUrl()); // e.g. the crate on screen was removed elsewhere
      return;
    }
    const fetchedPath = new URL(response.url || window.location.href, window.location.href).pathname;
    if (response.status !== 200 || response.redirected || fetchedPath !== window.location.pathname) {
      reload();
      return;
    }
    const html = await response.text();
    // Parsed into an inert document only to check it; htmx swaps the server's own markup.
    const fetched = new DOMParser().parseFromString(html, "text/html");
    if (selectors.some((sel) => !fetched.querySelector(sel))) {
      reload();
      return;
    }
    const token = fetched.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
    if (token) doc.querySelector('meta[name="csrf-token"]')?.setAttribute("content", token);
    const state = regionState(focusKey);
    selectors.forEach((sel) => {
      const target = doc.querySelector(sel);
      if (target) window.htmx.swap(target, html, { swapStyle: "outerHTML" }, { select: sel });
    });
    restoreState(state);
    if (drag) markCandidates();
  };
  const refreshQuietly = async (wanted, focusKey = null) => {
    try { await refresh(wanted, focusKey); } catch (error) { reload(); }
  };

  /* A 400 is almost always an expired CSRF token and a redirect an expired session: reload
     (with a fixed notice) instead of repeating a request that cannot succeed. */
  const recover = async (error, wanted, focusKey = null) => {
    const status = error?.status;
    if (status === 400) return reload("retry");
    if (status === 302) return reload();
    const message = status === 404
      ? "That crate or bucket no longer exists. The view has been refreshed."
      : status === 409
        ? "That change isn't possible. The view has been refreshed."
        : "That change couldn't be saved. The view has been refreshed.";
    toast(message, "danger");
    await refreshQuietly(wanted, focusKey);
  };

  const arrive = (selector) => {
    const node = selector && doc.querySelector(selector);
    if (!node) return;
    node.classList.add("is-arrived");
    node.addEventListener("animationend", () => node.classList.remove("is-arrived"), { once: true });
    window.setTimeout(() => node.classList.remove("is-arrived"), 1200);
  };

  /* After a crate is created on the board, open its menu so it can be named straight away. */
  const crateIds = () => new Set(Array.from(doc.querySelectorAll(`${BOARD} .crate-card[data-crate-id]`), (card) => card.dataset.crateId));
  const offerRename = (before) => {
    const card = Array.from(doc.querySelectorAll(`${BOARD} .crate-card[data-crate-id]`)).find((node) => !before.has(node.dataset.crateId));
    if (!card) return;
    arrive(`.crate-card[data-crate-id="${CSS.escape(card.dataset.crateId)}"]`);
    const menu = card.querySelector("details[data-menu]");
    const input = card.querySelector(".menu-rename input[name=name]");
    if (!menu || !input) return;
    menu.open = true;
    input.focus({ preventScroll: true });
    input.select();
    card.scrollIntoView({ block: "nearest" });
  };

  /* ------------------------------------------------------------ menus */
  const openMenus = () => Array.from(doc.querySelectorAll("details[data-menu][open]"));
  const closeMenus = (except) => openMenus().forEach((menu) => { if (menu !== except) menu.open = false; });
  doc.addEventListener("toggle", (event) => {
    const menu = event.target;
    if (menu instanceof HTMLDetailsElement && menu.matches("[data-menu]") && menu.open) closeMenus(menu);
  }, true);
  doc.addEventListener("click", (event) => {
    if (doc.querySelector("dialog[open]")) return; // e.g. the confirmation opened from a menu
    openMenus().forEach((menu) => { if (!menu.contains(event.target)) menu.open = false; });
  });
  // Capture phase: runs before mercury.js's shortcuts, which then see defaultPrevented.
  doc.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || doc.querySelector("dialog[open]")) return; // the dialog owns Esc
    const menu = openMenus().find((node) => node.contains(doc.activeElement)) || openMenus()[0];
    if (!menu) return;
    event.preventDefault();
    menu.open = false;
    menu.querySelector("summary")?.focus();
  }, true);

  /* -------------------------------------------- forms posted in place */
  doc.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-org-form")) return;
    if (event.defaultPrevented || !window.fetch) return; // e.g. a confirmation is pending
    const data = new FormData(form);
    if (event.submitter?.name) data.append(event.submitter.name, event.submitter.value);
    if (form.querySelector("[name=bucket_ids]") && !data.getAll("bucket_ids").length) {
      event.preventDefault();
      toast("Choose at least one bucket for the new crate.", "warning");
      form.querySelector("[name=bucket_ids]")?.focus();
      return;
    }
    event.preventDefault();
    const message = form.dataset.toast;
    const creates = form.action.endsWith("/crates") || data.get("crate_id") === "new";
    const before = crateIds();
    const focusKey = focusKeyOf(doc.activeElement) || focusKeyOf(form);
    // "Add bucket" on the crate view changes which rows the list holds; stars and the header's
    // crate menu change only the header and the sidebar.
    const wanted = scope(!!form.closest(".crate-chips"));
    const token = String(data.get("csrf_token") || "");
    form.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    closeMenus();
    enqueue(async () => {
      try {
        await post(form.action, data, { token });
      } catch (error) {
        await recover(error, wanted, focusKey);
        return;
      }
      await refreshQuietly(wanted, focusKey);
      if (message) toast(message);
      if (creates) offerRename(before);
    });
  });

  /* ------------------------------------------------------ drag state */
  let drag = null;
  let current = null;
  let pointerStart = null;
  doc.addEventListener("pointerdown", (event) => { pointerStart = event.target; }, true);

  const threadRows = () => Array.from(doc.querySelectorAll("[data-thread-list] [data-thread-row]"));
  const rowId = (row) => row.querySelector("[data-row-select]")?.value || row.id.replace(/^thread-/, "");
  // Only drags this page started carry our type; anything else (a file, a link) is ignored.
  const ours = (event) => Array.from(event.dataTransfer?.types || []).includes(MIME);

  const describe = (target) => {
    const state = drag;
    if (!state || !isElement(target)) return null;
    const type = target.dataset.drop;
    const inNav = !!target.closest(NAV);
    const name = target.dataset.name || "";
    if (state.kind === "threads") {
      if (type !== "bucket") return null;
      const bucketId = target.dataset.bucketId;
      if (state.rows.every((row) => (row.dataset.bucketId || "") === bucketId)) return null;
      const n = state.rows.length;
      return { label: n === 1 ? "Move here" : `Move ${n} here`, run: () => moveThreads(state.rows, bucketId, name) };
    }
    if (state.kind === "bucket") {
      const bucket = state;
      if (type === "crate") {
        if (target.dataset.crateId === bucket.crateId) return null;
        return { label: inNav ? "Add here" : `Add to ${name}`, run: () => placeBucket(bucket, target.dataset.crateId, name, target) };
      }
      if (type === "loose") {
        if (!bucket.crateId) return null;
        return { label: inNav ? "Take out" : "Take out of crate", run: () => placeBucket(bucket, "", "", target) };
      }
      if (type === "new-crate") {
        return { label: "Start a new crate", run: () => newCrate(bucket, null) };
      }
      if (type === "tile") {
        const otherId = target.dataset.bucketId;
        if (otherId === bucket.id || target.dataset.crateId) return null; // crate members: the card decides
        return { label: "Make a crate", run: () => newCrate(bucket, target) };
      }
      return null;
    }
    if (state.kind === "crate") {
      if (type !== "crate" || target.dataset.crateId === state.id || target.closest(NAV)) return null;
      return { label: `Combine into ${name}`, run: () => combineCrates(state, target) };
    }
    return null;
  };
  const findTarget = (node) => {
    let el = isElement(node) ? node : node?.parentElement;
    while (el && el !== doc.documentElement) {
      if (el.hasAttribute("data-drop")) {
        const found = describe(el);
        if (found) return { el, ...found };
      }
      el = el.parentElement;
    }
    return null;
  };
  const setCurrent = (found) => {
    const el = found?.el || null;
    if (current === el) return;
    if (current) {
      current.classList.remove("is-drop-target");
      current.removeAttribute("data-drop-label");
    }
    current = el;
    if (el) {
      el.classList.add("is-drop-target");
      el.setAttribute("data-drop-label", found.label);
    }
  };
  const clearCandidates = () => doc.querySelectorAll(".is-drop-candidate").forEach((node) => node.classList.remove("is-drop-candidate"));
  const markCandidates = () => {
    clearCandidates();
    doc.querySelectorAll("[data-drop]").forEach((node) => { if (describe(node)) node.classList.add("is-drop-candidate"); });
  };
  let ghost = null;
  const cleanup = () => {
    setCurrent(null);
    clearCandidates();
    doc.querySelectorAll(".is-dragging, .is-lifting").forEach((node) => node.classList.remove("is-dragging", "is-lifting"));
    doc.documentElement.classList.remove("drag-active");
    ghost?.remove();
    ghost = null;
    drag = null;
  };

  const threadGhost = (count) => {
    const node = doc.createElement("div");
    node.className = "drag-ghost";
    node.setAttribute("aria-hidden", "true");
    const badge = doc.createElement("span");
    badge.className = "drag-ghost-count";
    badge.textContent = String(count);
    node.append(badge, doc.createTextNode(count === 1 ? "conversation" : "conversations"));
    doc.body.append(node);
    return node;
  };

  doc.addEventListener("dragstart", (event) => {
    cleanup(); // never carry state over from a drag whose end we missed
    const dt = event.dataTransfer;
    const origin = isElement(event.target) ? event.target : null;
    if (!dt || !origin) return;
    const blocked = pointerStart && isElement(pointerStart) && pointerStart.closest(".menu-pop, input, textarea, select");
    const row = origin.closest("[data-thread-row]");
    const source = origin.closest("[data-drag]");
    if (blocked && (row || source)) {
      event.preventDefault();
      return;
    }
    if (source) {
      const kind = source.dataset.drag;
      drag = kind === "crate"
        ? { kind, source, id: source.dataset.crateId, name: source.dataset.name || "", combineUrl: source.dataset.combineUrl, card: source.closest(".crate-card") }
        : {
            kind: "bucket",
            source,
            id: source.dataset.bucketId,
            name: source.dataset.name || "",
            placeUrl: source.dataset.placeUrl,
            crateId: source.dataset.crateId || "",
            crateName: source.dataset.crateName || "",
            crateOrigin: source.dataset.crateOrigin || "",
            keeps: source.dataset.crateKeeps === "1",
          };
      dt.clearData();
      dt.setData(MIME, JSON.stringify({ kind: drag.kind, id: drag.id }));
    } else if (row) {
      const box = row.querySelector("[data-row-select]");
      const rows = box?.checked ? threadRows().filter((item) => item.querySelector("[data-row-select]")?.checked) : [row];
      drag = { kind: "threads", source: row, rows };
      dt.clearData();
      dt.setData(MIME, JSON.stringify({ kind: "threads", ids: rows.map(rowId) }));
      ghost = threadGhost(rows.length);
      dt.setDragImage(ghost, 18, 18);
    } else {
      return;
    }
    // dragend fires on the source node; if a refresh detaches it, it never reaches document.
    origin.addEventListener("dragend", cleanup, { once: true });
    dt.effectAllowed = "move";
    closeMenus();
    doc.documentElement.classList.add("drag-active");
    // Styles applied now are captured in the drag image; the placeholder look follows.
    const lifted = drag.kind === "threads" ? [] : [drag.source];
    lifted.forEach((node) => node.classList.add("is-lifting"));
    const moving = drag.kind === "threads" ? drag.rows : [drag.kind === "crate" ? drag.card : drag.source];
    window.requestAnimationFrame(() => {
      if (!drag) return;
      lifted.forEach((node) => node.classList.remove("is-lifting"));
      moving.forEach((node) => node?.classList.add("is-dragging"));
      markCandidates();
    });
  });

  // dragenter and dragover share one handler: the highlight follows the pointer immediately.
  const onDragOver = (event) => {
    if (!drag) return;
    if (!ours(event)) {
      cleanup(); // stale state meeting someone else's drag
      return;
    }
    const found = findTarget(event.target);
    setCurrent(found);
    if (!found) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };
  doc.addEventListener("dragenter", onDragOver);
  doc.addEventListener("dragover", onDragOver);
  doc.addEventListener("drop", (event) => {
    if (!drag) return;
    const found = ours(event) ? findTarget(event.target) : null;
    if (!found) {
      cleanup();
      return;
    }
    event.preventDefault();
    const run = found.run;
    cleanup();
    enqueue(run);
  });
  doc.addEventListener("dragend", cleanup);

  /* ---------------------------------------------------------- actions */
  const tileList = (container) => container?.querySelector(".tile-list");
  const syncEmpty = () => {
    doc.querySelectorAll(`${BOARD} .crate-card[data-crate-id]`).forEach((card) => {
      card.classList.toggle("is-empty", !card.querySelector(".tile"));
    });
    const tray = doc.querySelector(`${BOARD} .org-tray`);
    tray?.querySelector(".tray-empty")?.classList.toggle("is-shown", !tray.querySelector(".tile"));
  };
  // Instant feedback on the board; the refresh that follows reconciles with the server.
  const moveTileNow = (bucket, container) => {
    const tile = bucket.source;
    const list = tileList(container);
    if (!tile?.classList.contains("tile") || !list || !tile.closest(BOARD)) return;
    list.append(tile);
    syncEmpty();
  };
  // A move touching the crate on screen changes the list's rows.
  const placementScope = (fromId, toId) => {
    const shown = onScreenCrate();
    return scope(!!shown && (fromId === shown || toId === shown));
  };

  const undoFor = (bucket, toId) => {
    // Only offer undo when the previous place still exists (a user crate that lost its last
    // bucket is removed by the server).
    if (bucket.crateId && !bucket.keeps) return null;
    const previous = bucket.crateId;
    // Mercury's own filing goes back to Mercury rather than becoming a user placement.
    const fields = { crate_id: previous, ...(bucket.crateOrigin === "auto" ? { restore: "auto" } : {}) };
    return {
      label: "Undo",
      onClick: () => enqueue(async () => {
        const wanted = placementScope(toId, previous);
        try {
          await post(bucket.placeUrl, fields);
        } catch (error) {
          await recover(error, wanted);
          return;
        }
        await refreshQuietly(wanted);
        toast(previous ? `${bucket.name} is back in ${bucket.crateName}` : `${bucket.name} is back on its own`, "info");
        arrive(`${BOARD} .tile[data-bucket-id="${CSS.escape(bucket.id)}"]`);
      }),
    };
  };

  const placeBucket = async (bucket, crateId, crateName, target) => {
    // Taking the last bucket out of the crate on screen removes that crate, so go home
    // afterwards (with a fixed notice) instead of refreshing a page that no longer exists.
    const emptiesScreen = !!bucket.crateId && bucket.crateId === onScreenCrate() && !bucket.keeps;
    const wanted = placementScope(bucket.crateId, crateId);
    if (!emptiesScreen) moveTileNow(bucket, crateId ? target : doc.querySelector(`${BOARD} .org-tray`));
    try {
      await post(bucket.placeUrl, { crate_id: crateId });
    } catch (error) {
      await recover(error, wanted);
      return;
    }
    if (emptiesScreen) {
      notice("crate-emptied");
      window.location.assign(homeUrl());
      return;
    }
    await refreshQuietly(wanted);
    const message = crateId
      ? `Added ${bucket.name} to ${crateName}`
      : `Took ${bucket.name} out of ${bucket.crateName || "its crate"}`;
    toast(message, "success", undoFor(bucket, crateId));
    arrive(`${BOARD} .tile[data-bucket-id="${CSS.escape(bucket.id)}"]`);
  };

  const newCrate = async (bucket, otherTile) => {
    const before = crateIds();
    const fields = { crate_id: "new" };
    if (otherTile) fields.with_bucket_id = otherTile.dataset.bucketId;
    try {
      await post(bucket.placeUrl, fields);
    } catch (error) {
      await recover(error, scope());
      return;
    }
    await refreshQuietly(scope());
    const other = otherTile?.dataset.name;
    toast(other ? `Made a crate of ${bucket.name} and ${other}` : `Made a new crate for ${bucket.name}`);
    offerRename(before);
  };

  const combineCrates = async (crate, target) => {
    const list = tileList(target);
    if (list && crate.card) {
      crate.card.querySelectorAll(".tile").forEach((tile) => list.append(tile));
      syncEmpty();
    }
    try {
      await post(crate.combineUrl, { target_id: target.dataset.crateId });
    } catch (error) {
      await recover(error, scope());
      return;
    }
    await refreshQuietly(scope());
    toast(`Moved everything in ${crate.name} into ${target.dataset.name || "that crate"}`);
    arrive(`${BOARD} .crate-card[data-crate-id="${CSS.escape(target.dataset.crateId)}"]`);
  };

  /* Moved conversations are updated where they are, so loaded older pages and the scroll
     position survive: a row leaves when this list no longer includes its new bucket, and
     otherwise just shows the new bucket. */
  const listKeeps = (bucketId) => {
    const region = doc.querySelector(LIST);
    const kind = region?.dataset.listKind || "other";
    if (kind === "unsorted") return false;
    if (kind === "bucket" || kind === "crate") return (region.dataset.listBuckets || "").split(" ").includes(bucketId);
    return true;
  };
  const showBucket = (row, bucketId, name) => {
    row.dataset.bucketId = bucketId;
    const badge = row.querySelector(".row-meta > .badge-m");
    if (!badge) return;
    const unsorted = bucketId === "unsorted";
    badge.classList.toggle("badge-muted", unsorted);
    badge.classList.toggle("badge-bucket", !unsorted);
    if (badge.lastElementChild) badge.lastElementChild.textContent = name;
    const icon = badge.querySelector("svg");
    const pail = doc.querySelector(`[data-bucket-id="${CSS.escape(bucketId)}"] svg`)?.cloneNode(true)
      || doc.querySelector('[data-drop="bucket"] svg')?.cloneNode(true);
    if (icon && pail) {
      pail.setAttribute("class", "icon icon-xs");
      icon.replaceWith(pail);
    }
  };
  const placeRows = (rows, bucketId, name) => {
    const keep = listKeeps(bucketId);
    rows.forEach((stale) => {
      const row = doc.getElementById(stale.id) || stale;
      row.classList.remove("is-moving");
      if (!keep) {
        row.remove();
        return;
      }
      showBucket(row, bucketId, name);
      const box = row.querySelector("[data-row-select]");
      if (box?.checked) {
        box.checked = false;
        box.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    // mercury.js recounts the shown rows and prunes the selection on input.
    doc.querySelector("[data-list-filter]")?.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const moveThreads = async (rows, bucketId, bucketName) => {
    rows.forEach((row) => row.classList.add("is-moving"));
    const moved = [];
    let errors = 0;
    for (const row of rows) {
      try {
        await post(row.dataset.moveUrl, { bucket_id: bucketId }, { headers: { "X-Mercury-Bulk": "1" } });
        moved.push(row);
      } catch (error) {
        if (error.status === 400 || error.status === 302) {
          await recover(error, [NAV]);
          return;
        }
        errors += 1;
      }
    }
    rows.forEach((row) => row.classList.remove("is-moving"));
    placeRows(moved, bucketId, bucketName);
    // Refetch the list only once it has emptied, to show its empty state or the next rows.
    const emptied = !doc.querySelector("[data-thread-list] [data-thread-row]");
    await refreshQuietly(emptied ? [NAV, LIST] : [NAV]);
    if (errors) {
      toast(`${moved.length} moved to ${bucketName}; ${plural(errors, "conversation", "conversations")} couldn't be moved.`, "danger");
    } else {
      toast(`Moved ${plural(moved.length, "conversation", "conversations")} to ${bucketName}. Mercury will keep ${moved.length === 1 ? "it" : "them"} there.`);
    }
  };
})();
