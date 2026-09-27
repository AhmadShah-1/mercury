"use strict";
// Runs synchronously in <head>: mark JS availability and apply saved display preferences before
// first paint. Only the literal "light"/"dark" theme, a collapsed-sidebar flag, and a list width
// in pixels are stored; never any mailbox content.
(function () {
  var root = document.documentElement;
  root.classList.remove("no-js");
  root.classList.add("js");
  var saved = null;
  var nav = null;
  var listWidth = NaN;
  try {
    saved = window.localStorage.getItem("mercury-theme");
    nav = window.localStorage.getItem("mercury-nav");
    listWidth = parseInt(window.localStorage.getItem("mercury-list-width"), 10);
  } catch (error) {
    saved = null;
  }
  if (saved === "light" || saved === "dark") {
    root.setAttribute("data-theme", saved);
  }
  var dark =
    saved === "dark" ||
    (saved !== "light" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.setAttribute("data-bs-theme", dark ? "dark" : "light");
  if (nav === "collapsed") root.setAttribute("data-nav", "collapsed");
  // CSSOM custom property (allowed under style-src 'self'); CSS clamps it to the window.
  if (listWidth >= 280 && listWidth <= 1600) root.style.setProperty("--ws-list-w", listWidth + "px");
})();
