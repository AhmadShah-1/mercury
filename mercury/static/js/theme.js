"use strict";
// Runs synchronously in <head>: mark JS availability and apply a saved theme before first paint.
// Only the literal "light"/"dark" preference is stored; never any mailbox content.
(function () {
  var root = document.documentElement;
  root.classList.remove("no-js");
  root.classList.add("js");
  var saved = null;
  try {
    saved = window.localStorage.getItem("mercury-theme");
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
})();
