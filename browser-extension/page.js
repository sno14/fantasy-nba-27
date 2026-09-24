(function () {
  "use strict";

  const CHANNEL = "__fantasyNbaDraft";
  const picks = new Map();
  let lastSignature = "";
  let lastSentAt = 0;
  let scanQueued = false;
  let reactScanRunning = false;
  let cachedFiberRoot = null;

  const idle = window.requestIdleCallback
    ? (callback) => window.requestIdleCallback(callback, { timeout: 250 })
    : (callback) => setTimeout(() => callback({ timeRemaining: () => 8 }), 0);

  function normalizePick(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const player = value.player && typeof value.player === "object" ? value.player : null;
    const athlete = value.athlete && typeof value.athlete === "object" ? value.athlete : null;
    const espnId = Number(value.playerId ?? value.player_id ?? value.espnPlayerId
      ?? player?.id ?? player?.playerId ?? athlete?.id ?? athlete?.playerId ?? 0);
    const name = value.playerName ?? value.fullName ?? value.displayName
      ?? player?.fullName ?? player?.displayName ?? player?.name
      ?? athlete?.fullName ?? athlete?.displayName ?? athlete?.name ?? null;
    const eligibleSlots = value.eligibleSlots ?? player?.eligibleSlots ?? athlete?.eligibleSlots;
    let overall = Number(value.overallPickNumber ?? value.overall_pick_number ?? value.overall
      ?? value.pickNumber ?? value.pick_number ?? 0);
    const round = Number(value.roundId ?? value.round_id ?? value.roundNumber ?? value.round ?? 0);
    const roundPick = Number(value.roundPickNumber ?? value.round_pick_number
      ?? value.roundPick ?? 0);
    if (!(overall > 0) && round > 0 && roundPick > 0) {
      overall = (round - 1) * 12 + roundPick;
    }
    if (!(espnId > 0) || (!(overall > 0) && (!(round > 0) || !(roundPick > 0)))) return null;
    return {
      espn_player_id: espnId,
      name: typeof name === "string" && name.trim() ? name.trim() : null,
      eligible_slots: Array.isArray(eligibleSlots) ? eligibleSlots : null,
      team_id: Number(value.teamId ?? value.team_id ?? 0) || null,
      overall: overall || null,
      round_id: round || null,
      round_pick: roundPick || null,
    };
  }

  function absorb(root) {
    if (!root || typeof root !== "object") return;
    const seen = new WeakSet();
    const stack = [{ value: root, depth: 0 }];
    let visited = 0;
    while (stack.length && visited++ < 1500) {
      const { value, depth } = stack.pop();
      if (!value || typeof value !== "object" || depth > 8 || seen.has(value)) continue;
      seen.add(value);
      const pick = normalizePick(value);
      if (pick) {
        const key = pick.overall ? `o${pick.overall}` : `r${pick.round_id}p${pick.round_pick}`;
        picks.set(key, pick);
        continue;
      }
      const values = Array.isArray(value) ? value : Object.values(value);
      for (let i = 0; i < values.length && i < 100; i += 1) {
        if (values[i] && typeof values[i] === "object") {
          stack.push({ value: values[i], depth: depth + 1 });
        } else if (typeof values[i] === "string" && values[i].length < 200000) {
          try {
            const nested = JSON.parse(values[i]);
            if (nested && typeof nested === "object") stack.push({ value: nested, depth: depth + 1 });
          } catch (_) { /* ordinary text */ }
        }
      }
    }
    emit();
  }

  function absorbText(text) {
    if (typeof text !== "string" || text.length > 2000000) return;
    try {
      absorb(JSON.parse(text));
      return;
    } catch (_) { /* some transports wrap JSON in a text envelope */ }
    const first = text.indexOf("{");
    const last = text.lastIndexOf("}");
    if (first >= 0 && last > first) {
      try { absorb(JSON.parse(text.slice(first, last + 1))); } catch (_) { /* not JSON */ }
    }
  }

  function emit(force) {
    const ordered = [...picks.values()]
      .filter((pick) => pick.overall > 0)
      .sort((a, b) => a.overall - b.overall);
    const signature = ordered.length
      ? ordered.map((pick) => `${pick.overall}:${pick.espn_player_id || pick.name}`).join("|")
      : "empty";
    if (!force && signature === lastSignature && Date.now() - lastSentAt < 5000) return;
    lastSignature = signature;
    lastSentAt = Date.now();
    const query = new URLSearchParams(location.search);
    window.postMessage({
      [CHANNEL]: true,
      payload: {
        league_id: query.get("leagueId") || "",
        season: Number(query.get("seasonId") || 0),
        my_team_id: Number(query.get("teamId") || 0),
        picks: ordered,
      },
    }, "*");
  }

  // Observe JSON already delivered to the ESPN page. This is read-only and never makes picks.
  const NativeWebSocket = window.WebSocket;
  if (NativeWebSocket) {
    class ObservedWebSocket extends NativeWebSocket {
      constructor(url, protocols) {
        super(...(protocols === undefined ? [url] : [url, protocols]));
        this.addEventListener("message", (event) => absorbText(event.data));
      }
    }
    Object.defineProperties(ObservedWebSocket, {
      CONNECTING: { value: NativeWebSocket.CONNECTING },
      OPEN: { value: NativeWebSocket.OPEN },
      CLOSING: { value: NativeWebSocket.CLOSING },
      CLOSED: { value: NativeWebSocket.CLOSED },
    });
    window.WebSocket = ObservedWebSocket;
  }

  const nativeFetch = window.fetch;
  if (nativeFetch) {
    window.fetch = function (...args) {
      return nativeFetch.apply(this, args).then((response) => {
        const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
        if (/espn\.com/i.test(url)) response.clone().json().then(absorb).catch(() => {});
        return response;
      });
    };
  }

  const xhrOpen = XMLHttpRequest.prototype.open;
  const xhrSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (_method, url) {
    this.__fantasyNbaUrl = String(url || "");
    return xhrOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    this.addEventListener("load", function () {
      if (!/espn\.com/i.test(this.__fantasyNbaUrl || "")) return;
      if (!this.responseType || this.responseType === "text") absorbText(this.responseText);
    });
    return xhrSend.apply(this, arguments);
  };

  // Bounded DOM fallback: inspect at most 250 elements explicitly labelled as pick history.
  function scanVisiblePickHistory() {
    const nodes = document.querySelectorAll(
      "[data-testid*='pick'], [data-testid*='draft'], [class*='pick-history'], "
      + "[class*='PickHistory'], [class*='draft-history'], [class*='DraftHistory']",
    );
    const teamCount = 12;
    for (let i = 0; i < nodes.length && i < 250; i += 1) {
      const text = (nodes[i].textContent || "").replace(/\s+/g, " ").trim();
      if (!text || text.length > 220) continue;
      const match = text.match(
        /(?:#|pick\s*)?(\d{1,3})\D{0,12}([\p{L}][\p{L} .'\-]{2,45}?)\s+(PG|SG|SF|PF|C)\b/iu,
      );
      if (!match) continue;
      const overall = Number(match[1]);
      if (!(overall > 0 && overall <= 300)) continue;
      picks.set(`o${overall}`, {
        name: match[2].trim(),
        overall,
        round_id: Math.floor((overall - 1) / teamCount) + 1,
        round_pick: ((overall - 1) % teamCount) + 1,
        team_id: null,
      });
    }
    emit();
  }

  function queueDomScan() {
    if (scanQueued) return;
    scanQueued = true;
    setTimeout(() => {
      scanQueued = false;
      scanVisiblePickHistory();
    }, 300);
  }

  function findFiberRoot() {
    if (cachedFiberRoot) return cachedFiberRoot;
    const preferred = [document.getElementById("espnfitt"), document.getElementById("root")]
      .filter(Boolean);
    const candidates = [...preferred, ...Array.from(document.querySelectorAll("*")).slice(0, 800)];
    for (const element of candidates) {
      const key = Object.keys(element).find((name) =>
        name.startsWith("__reactFiber$") || name.startsWith("__reactInternalInstance$"));
      if (!key) continue;
      let fiber = element[key];
      while (fiber?.return) fiber = fiber.return;
      cachedFiberRoot = fiber;
      return fiber;
    }
    return null;
  }

  // ESPN keeps the live pick list in React state on some draft clients. Scan it cooperatively,
  // yielding after four milliseconds so a large draft-room tree cannot freeze the page.
  function scanReactState() {
    if (reactScanRunning) return;
    const root = findFiberRoot();
    if (!root) return;
    reactScanRunning = true;
    const fiberStack = [root];
    const seenFibers = new Set();
    const valueRoots = [];
    let fiberCount = 0;

    function fiberSlice(deadline) {
      const sliceStarted = performance.now();
      while (fiberStack.length && performance.now() - sliceStarted < 4
             && fiberCount++ < 50000) {
        const fiber = fiberStack.pop();
        if (!fiber || seenFibers.has(fiber)) continue;
        seenFibers.add(fiber);
        if (fiber.memoizedProps) valueRoots.push(fiber.memoizedProps);
        if (fiber.memoizedState) valueRoots.push(fiber.memoizedState);
        if (fiber.child) fiberStack.push(fiber.child);
        if (fiber.sibling) fiberStack.push(fiber.sibling);
      }
      if (fiberStack.length && fiberCount < 50000) {
        idle(fiberSlice);
      } else {
        idle(valueSliceStart);
      }
    }

    function valueSliceStart(deadline) {
      const stack = valueRoots.map((value) => ({ value, depth: 0 }));
      const seen = new WeakSet();
      let visited = 0;
      function valueSlice(nextDeadline) {
        const sliceStarted = performance.now();
        while (stack.length && performance.now() - sliceStarted < 4
               && visited++ < 50000) {
          const { value, depth } = stack.pop();
          if (!value || typeof value !== "object" || depth > 7 || seen.has(value)) continue;
          seen.add(value);
          const pick = normalizePick(value);
          if (pick) {
            const key = pick.overall ? `o${pick.overall}` : `r${pick.round_id}p${pick.round_pick}`;
            picks.set(key, pick);
            continue;
          }
          const values = Array.isArray(value) ? value : Object.values(value);
          for (let i = 0; i < values.length && i < 80; i += 1) {
            if (values[i] && typeof values[i] === "object") {
              stack.push({ value: values[i], depth: depth + 1 });
            }
          }
        }
        if (stack.length && visited < 50000) {
          idle(valueSlice);
        } else {
          reactScanRunning = false;
          emit();
        }
      }
      valueSlice(deadline);
    }

    idle(fiberSlice);
  }

  const start = () => {
    new MutationObserver(queueDomScan).observe(document.body, { childList: true, subtree: true });
    scanVisiblePickHistory();
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
  setInterval(() => emit(true), 5000);
  setInterval(scanReactState, 3000);
  setTimeout(scanReactState, 1200);
})();
