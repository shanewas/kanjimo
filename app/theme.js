// Applies the saved theme before first paint. A classic blocking script, not
// a module, so it runs before the stylesheet; the key is THEME_KEY in app.js.
try {
  if (localStorage.getItem("jstudy.theme") === "dark") document.documentElement.setAttribute("data-theme", "dark");
} catch (e) { /* storage blocked: light theme */ }
