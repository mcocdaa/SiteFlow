(function () {
  "use strict";

  var PAD = 16;
  var GAP = 22;
  var DRAG_THRESHOLD = 6;
  var KEY_STEP = 20;
  var KEY_STEP_LARGE = 48;
  var BASE_ANGLES = [-2.2, 1.8, -1.5, 2.4, -1.9, 1.3];

  function initDesk() {
    if (!document.body.classList.contains("space-layout-desk")) return;
    var grid = document.querySelector("main .grid");
    if (!grid || grid.dataset.deskInit === "1") return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(":scope > .card"));
    if (!cards.length) return;
    grid.dataset.deskInit = "1";

    var bar = document.querySelector("[data-space-desk-bar]");
    var slug = (bar && bar.dataset.projectSlug) || window.location.pathname;
    var storageKey = "sf_desk_pos_" + slug;
    var liveEl = bar ? bar.querySelector("[data-desk-live]") : null;
    var shuffleBtn = bar ? bar.querySelector("[data-desk-shuffle]") : null;
    var resetBtn = bar ? bar.querySelector("[data-desk-reset]") : null;

    var state = {};
    var topZ = 10;
    var liveTimer = 0;

    function announce(message) {
      if (!liveEl || !message) return;
      liveEl.textContent = "";
      window.clearTimeout(liveTimer);
      window.requestAnimationFrame(function () {
        liveEl.textContent = message;
      });
      liveTimer = window.setTimeout(function () {
        liveEl.textContent = "";
      }, 1500);
    }

    function t(key, fallback) {
      if (window.SiteFlowI18n && window.SiteFlowI18n.t) {
        var val = window.SiteFlowI18n.t(key);
        if (val && val !== key) return val;
      }
      return fallback;
    }

    function readSaved() {
      try {
        var raw = localStorage.getItem(storageKey);
        if (!raw) return {};
        var parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : {};
      } catch (_) {
        return {};
      }
    }

    function saveState() {
      try {
        localStorage.setItem(storageKey, JSON.stringify(state));
      } catch (_) {}
    }

    function computeCardWidth() {
      var w = grid.clientWidth || 900;
      var cols = w < 600 ? 1 : w < 900 ? 2 : 3;
      var inner = Math.max(220, w - PAD * 2 - GAP * (cols - 1));
      return Math.min(310, Math.max(210, Math.floor(inner / cols)));
    }

    function cardSize(card, fallbackWidth) {
      var w = card.offsetWidth || fallbackWidth;
      var h = card.offsetHeight || 260;
      return { w: w, h: h };
    }

    function syncCanvasHeight() {
      var maxBottom = 500;
      var cardW = computeCardWidth();
      cards.forEach(function (card) {
        var id = card.dataset.slug || "";
        var pos = state[id];
        if (!pos) return;
        var sz = cardSize(card, cardW);
        var bottom = pos.y + sz.h + PAD * 2;
        if (bottom > maxBottom) maxBottom = bottom;
      });
      grid.style.height = Math.ceil(maxBottom) + "px";
    }

    function clampPos(card, x, y) {
      var cardW = computeCardWidth();
      var sz = cardSize(card, cardW);
      var maxX = Math.max(PAD, (grid.clientWidth || 900) - sz.w - PAD);
      var maxY = Math.max(PAD, 2400);
      return {
        x: Math.round(Math.max(PAD, Math.min(x, maxX))),
        y: Math.round(Math.max(PAD, Math.min(y, maxY)))
      };
    }

    function applyCardPos(card, pos) {
      card.style.left = pos.x + "px";
      card.style.top = pos.y + "px";
      card.style.zIndex = String(pos.z || 1);
      card.style.setProperty("--sf-desk-rot", (pos.rot || 0).toFixed(2) + "deg");
    }

    function neatPositions() {
      var w = grid.clientWidth || 900;
      var cardW = computeCardWidth();
      var cols = Math.max(1, Math.floor((w - PAD * 2 + GAP) / (cardW + GAP)));
      var colHeights = [];
      for (var c = 0; c < cols; c += 1) colHeights.push(PAD);
      var out = {};
      cards.forEach(function (card, idx) {
        card.style.width = cardW + "px";
        var col = idx % cols;
        var x = PAD + col * (cardW + GAP);
        var y = colHeights[col];
        var h = card.offsetHeight || 260;
        colHeights[col] = y + h + GAP;
        var id = card.dataset.slug || ("card-" + idx);
        out[id] = {
          x: Math.round(x),
          y: Math.round(y),
          rot: BASE_ANGLES[idx % BASE_ANGLES.length],
          z: idx + 1
        };
      });
      return out;
    }

    function applyAll(nextMap) {
      var cardW = computeCardWidth();
      cards.forEach(function (card, idx) {
        card.style.width = cardW + "px";
        var id = card.dataset.slug || ("card-" + idx);
        var raw = nextMap[id];
        var clamped = clampPos(card, raw.x, raw.y);
        var zVal = typeof raw.z === "number" ? raw.z : idx + 1;
        if (zVal > topZ) topZ = zVal;
        state[id] = {
          x: clamped.x,
          y: clamped.y,
          rot: typeof raw.rot === "number" ? raw.rot : BASE_ANGLES[idx % BASE_ANGLES.length],
          z: zVal
        };
        applyCardPos(card, state[id]);
      });
      syncCanvasHeight();
    }

    function initialLayout() {
      grid.classList.add("is-desk-ready");
      var neat = neatPositions();
      var saved = readSaved();
      var merged = {};
      cards.forEach(function (card, idx) {
        var id = card.dataset.slug || ("card-" + idx);
        var s = saved[id];
        if (s && typeof s.x === "number" && typeof s.y === "number") {
          merged[id] = {
            x: s.x,
            y: s.y,
            rot: typeof s.rot === "number" ? s.rot : neat[id].rot,
            z: typeof s.z === "number" ? s.z : neat[id].z
          };
        } else {
          merged[id] = neat[id];
        }
      });
      applyAll(merged);
    }

    function shuffleCards() {
      var w = grid.clientWidth || 900;
      var cardW = computeCardWidth();
      var cols = Math.max(1, Math.floor((w - PAD * 2 + GAP) / (cardW + GAP)));
      var rows = Math.ceil(cards.length / cols);
      var cellW = Math.max(cardW + 12, (w - PAD * 2) / cols);
      var cellH = 290;
      var slots = [];
      for (var r = 0; r < rows; r += 1) {
        for (var c = 0; c < cols; c += 1) {
          slots.push({ r: r, c: c });
        }
      }
      for (var i = slots.length - 1; i > 0; i -= 1) {
        var j = Math.floor(Math.random() * (i + 1));
        var tmp = slots[i];
        slots[i] = slots[j];
        slots[j] = tmp;
      }
      var nextMap = {};
      cards.forEach(function (card, idx) {
        var id = card.dataset.slug || ("card-" + idx);
        var slot = slots[idx] || { r: Math.floor(idx / cols), c: idx % cols };
        var jitterX = (Math.random() - 0.5) * Math.min(70, Math.max(24, cellW - cardW + 40));
        var jitterY = (Math.random() - 0.5) * 64;
        var baseX = PAD + slot.c * cellW + jitterX;
        var baseY = PAD + slot.r * cellH + jitterY;
        var rot = (Math.random() - 0.5) * 9.5;
        topZ += 1;
        nextMap[id] = { x: baseX, y: baseY, rot: rot, z: topZ };
      });
      applyAll(nextMap);
      saveState();
      announce(t("ext.space_layout.announced_shuffle", "已随机打乱卡片摆放位置"));
    }

    function resetCards() {
      var neat = neatPositions();
      applyAll(neat);
      try {
        localStorage.removeItem(storageKey);
      } catch (_) {}
      announce(t("ext.space_layout.announced_reset", "已将全部卡片整齐归位"));
    }

    cards.forEach(function (card, idx) {
      var id = card.dataset.slug || ("card-" + idx);
      card.setAttribute("draggable", "false");
      var drag = null;

      card.addEventListener("click", function (event) {
        if (card.dataset.justDragged === "1") {
          event.preventDefault();
          event.stopPropagation();
          delete card.dataset.justDragged;
        }
      });

      card.addEventListener("pointerdown", function (event) {
        if (event.button !== 0) return;
        if (event.target.closest("button, input, select, textarea")) return;
        var cur = state[id];
        if (!cur) return;
        drag = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          origX: cur.x,
          origY: cur.y,
          tx: 0,
          ty: 0,
          active: false
        };
      });

      card.addEventListener("pointermove", function (event) {
        if (!drag || event.pointerId !== drag.pointerId) return;
        var dx = event.clientX - drag.startX;
        var dy = event.clientY - drag.startY;
        if (!drag.active) {
          if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
          drag.active = true;
          topZ += 1;
          state[id].z = topZ;
          card.style.zIndex = String(topZ);
          card.classList.add("is-dragging");
          try {
            card.setPointerCapture(event.pointerId);
          } catch (_) {}
        }
        var clamped = clampPos(card, drag.origX + dx, drag.origY + dy);
        drag.tx = clamped.x - drag.origX;
        drag.ty = clamped.y - drag.origY;
        card.style.transform = "translate3d(" + drag.tx + "px, " + drag.ty + "px, 0) rotate(0deg)";
      });

      function finishDrag(commit) {
        if (!drag) return;
        var wasActive = drag.active;
        var finalX = drag.origX + drag.tx;
        var finalY = drag.origY + drag.ty;
        drag = null;
        if (!wasActive) return;
        card.classList.remove("is-dragging");
        card.style.transform = "";
        if (commit) {
          var clamped = clampPos(card, finalX, finalY);
          state[id].x = clamped.x;
          state[id].y = clamped.y;
          applyCardPos(card, state[id]);
          syncCanvasHeight();
          saveState();
          card.dataset.justDragged = "1";
          window.setTimeout(function () {
            delete card.dataset.justDragged;
          }, 120);
        }
      }

      card.addEventListener("pointerup", function (event) {
        if (!drag || event.pointerId !== drag.pointerId) return;
        finishDrag(true);
      });

      card.addEventListener("pointercancel", function (event) {
        if (!drag || event.pointerId !== drag.pointerId) return;
        finishDrag(false);
      });

      card.addEventListener("lostpointercapture", function () {
        if (drag && drag.active) finishDrag(true);
      });

      card.addEventListener("keydown", function (event) {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        var step = event.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
        var dx = 0;
        var dy = 0;
        var dirLabel = "";
        if (event.key === "ArrowLeft") {
          dx = -step;
          dirLabel = t("ext.space_layout.moved_left", "向左移动");
        } else if (event.key === "ArrowRight") {
          dx = step;
          dirLabel = t("ext.space_layout.moved_right", "向右移动");
        } else if (event.key === "ArrowUp") {
          dy = -step;
          dirLabel = t("ext.space_layout.moved_up", "向上移动");
        } else if (event.key === "ArrowDown") {
          dy = step;
          dirLabel = t("ext.space_layout.moved_down", "向下移动");
        } else {
          return;
        }
        event.preventDefault();
        var cur = state[id];
        if (!cur) return;
        topZ += 1;
        var clamped = clampPos(card, cur.x + dx, cur.y + dy);
        cur.x = clamped.x;
        cur.y = clamped.y;
        cur.z = topZ;
        applyCardPos(card, cur);
        syncCanvasHeight();
        saveState();
        var title = card.dataset.title || id;
        announce(title + " " + dirLabel);
      });
    });

    if (shuffleBtn) shuffleBtn.addEventListener("click", shuffleCards);
    if (resetBtn) resetBtn.addEventListener("click", resetCards);

    var resizeTimer = 0;
    window.addEventListener("resize", function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(function () {
        applyAll(state);
      }, 100);
    });

    initialLayout();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDesk, { once: true });
  } else {
    initDesk();
  }
})();
