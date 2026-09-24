(function () {
  "use strict";

  let badge;

  function show(message, ok) {
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "fantasy-nba-draft-bridge-status";
      Object.assign(badge.style, {
        position: "fixed",
        right: "12px",
        bottom: "12px",
        zIndex: "2147483647",
        padding: "7px 10px",
        borderRadius: "7px",
        font: "600 12px system-ui, sans-serif",
        color: "white",
        boxShadow: "0 2px 10px rgba(0,0,0,.35)",
      });
      (document.body || document.documentElement).appendChild(badge);
    }
    badge.style.background = ok ? "#16784a" : "#9b3a25";
    badge.textContent = message;
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || event.data.__fantasyNbaDraft !== true) return;
    const payload = event.data.payload;
    if (!payload || !Array.isArray(payload.picks)) return;
    chrome.runtime.sendMessage(
      { type: "fantasy-nba-draft-sync", payload },
      (response) => {
        if (chrome.runtime.lastError) {
          show(`Draft bridge: ${chrome.runtime.lastError.message}`, false);
        } else if (!response || !response.ok) {
          show(`Draft bridge: ${response?.error || "local app unavailable"}`, false);
        } else {
          show(`Draft bridge connected: ${response.n_picks} picks`, true);
        }
      },
    );
  });

  window.addEventListener("DOMContentLoaded", () => show("Draft bridge: finding picksâ€¦", false),
    { once: true });
})();
