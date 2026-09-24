"use strict";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "fantasy-nba-draft-sync") return false;
  fetch("http://127.0.0.1:8787/api/draft/browser-sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.payload),
  })
    .then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `Local app returned ${response.status}`);
      sendResponse({ ok: true, ...body });
    })
    .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
  return true;
});
