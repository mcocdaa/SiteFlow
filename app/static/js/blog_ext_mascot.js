(function () {
  "use strict";
  var root = document.querySelector("[data-mascot-root]") || document.querySelector("[data-sf-mascot]");
  if (!root) return;

  var bubble = root.querySelector("[data-mascot-bubble]");
  var bubbleBody = root.querySelector("[data-mascot-bubble-body]");

  var stage = root.querySelector("[data-mascot-stage]") || root.querySelector(".sf-mascot-stage");
  var trigger = root.querySelector("[data-mascot-trigger]");
  var poseImg = root.querySelector("[data-mascot-pose-img]");
  var zoomBtn = root.querySelector("[data-mascot-zoom]");
  var zoomInIcon = zoomBtn ? zoomBtn.querySelector(".sf-mascot-ico-zoom-in") : null;
  var zoomOutIcon = zoomBtn ? zoomBtn.querySelector(".sf-mascot-ico-zoom-out") : null;
  var topBtn = root.querySelector("[data-mascot-top]");
  var collapseBtn = root.querySelector("[data-mascot-toggle]");
  var expandBtn = root.querySelector("[data-mascot-expand]");
  var configNode = root.querySelector("[data-mascot-config]");

  var chatForm = root.querySelector("[data-mascot-chat-form]");
  var chatInput = root.querySelector("[data-mascot-chat-input]");
  var chatResetBtn = root.querySelector("[data-mascot-chat-reset]");
  var chatSendBtn = root.querySelector("[data-mascot-chat-send]");
  var chatStopBtn = root.querySelector("[data-mascot-chat-stop]");

  function isSafePoseUrl(url) {
    if (typeof url !== "string") return false;
    var cleaned = url.trim();
    if (!cleaned || /[\x00-\x20\x7f]/.test(cleaned)) return false;
    return cleaned.indexOf("/static/") === 0 || cleaned.indexOf("/media/") === 0;
  }

  var config = {
    slug: "default",
    page: "list",
    post_slug: "",
    project_title: "",
    post_title: "",
    post_words: 0,
    draggable: true,
    greeting: "",
    tips: [],
    chat_enabled: false,
    chat_url: "",
    character: "cat",
    character_kind: "inline_svg",
    poses: {}
  };

  if (configNode) {
    try {
      var parsed = JSON.parse(configNode.textContent || "{}");
      if (parsed && typeof parsed === "object") {
        if (typeof parsed.slug === "string" && parsed.slug.trim()) config.slug = parsed.slug.trim();
        if (typeof parsed.page === "string" && parsed.page.trim()) config.page = parsed.page.trim();
        if (typeof parsed.post_slug === "string") config.post_slug = parsed.post_slug;
        if (typeof parsed.project_title === "string") config.project_title = parsed.project_title.trim();
        if (typeof parsed.post_title === "string") config.post_title = parsed.post_title.trim();
        if (typeof parsed.post_words === "number" && isFinite(parsed.post_words) && parsed.post_words > 0) {
          config.post_words = Math.floor(parsed.post_words);
        }
        if (typeof parsed.draggable === "boolean") config.draggable = parsed.draggable;
        if (typeof parsed.greeting === "string") config.greeting = parsed.greeting;
        if (Array.isArray(parsed.tips)) {
          config.tips = parsed.tips
            .filter(function (v) { return typeof v === "string"; })
            .map(function (v) { return v.trim(); })
            .filter(function (v) { return Boolean(v) && v.charAt(0) !== "#"; });
        }
        if (typeof parsed.chat_enabled === "boolean") config.chat_enabled = parsed.chat_enabled;
        if (typeof parsed.chat_url === "string") config.chat_url = parsed.chat_url;
        if (typeof parsed.character === "string") config.character = parsed.character;
        if (
          parsed.character_kind === "inline_svg" ||
          parsed.character_kind === "pose_svg" ||
          parsed.character_kind === "custom"
        ) {
          config.character_kind = parsed.character_kind;
        }
        if (parsed.poses && typeof parsed.poses === "object") {
          var poseKeys = ["idle", "thinking", "speaking", "tap"];
          for (var pk = 0; pk < poseKeys.length; pk += 1) {
            var poseKey = poseKeys[pk];
            if (isSafePoseUrl(parsed.poses[poseKey])) {
              config.poses[poseKey] = parsed.poses[poseKey].trim();
            }
          }
        }
      }
    } catch (e) {}
  }

  var hasPoseThinking = Boolean(poseImg && config.poses.thinking);
  var hasPoseSpeaking = Boolean(poseImg && config.poses.speaking);
  var hasPoseTap = Boolean(poseImg && config.poses.tap);
  root.classList.toggle("has-pose-thinking", hasPoseThinking);
  root.classList.toggle("has-pose-speaking", hasPoseSpeaking);
  root.classList.toggle("has-pose-tap", hasPoseTap);

  if (poseImg && config.poses.idle) {
    setTimeout(function () {
      var preloadKeys = ["thinking", "speaking", "tap"];
      for (var i = 0; i < preloadKeys.length; i += 1) {
        var poseUrl = config.poses[preloadKeys[i]];
        if (poseUrl) {
          var pre = new Image();
          pre.src = poseUrl;
        }
      }
    }, 400);
  }

  var COLLAPSE_KEY = "sf_mascot_collapsed_" + config.slug;
  var GREET_KEY = "sf_mascot_greeted_" + config.slug;
  var POS_KEY = "sf_mascot_pos_" + config.slug;
  var ZOOM_KEY = "sf_mascot_zoom_" + config.slug;
  var VIEWPORT_MARGIN = 20;
  var DRAG_THRESHOLD = 5;
  var DOCK_COMPACT_WIDTH = 148;
  var DOCK_EXPANDED_WIDTH = 268;
  var AI_READ_FADE_DELAY = 8000;
  var AI_LEAVE_FADE_DELAY = 1600;
  var MAX_HISTORY_ASSISTANT_CHARS = 6000;
  var TIP_TOKEN_RE = /\{(progress|heading|title|site|words|time)\}/g;

  var hideTimer = null;
  var aiFadeTimer = null;
  var dockHideTimer = null;
  var dockWidthTimer = null;
  var speakBurstTimer = null;
  var tapPoseTimer = null;
  var poseSwapTimer = null;
  var bounceTimer = null;
  var zoomClampTimer = null;
  var stageHovered = false;
  var bubbleHovered = false;
  var dockHovered = false;
  var aiBubbleFaded = false;
  var pendingDockWidth = null;
  var bubbleMode = "none";
  var mascotMood = "idle";
  var mascotAction = "";
  var currentPose = poseImg ? (poseImg.getAttribute("data-mascot-pose") || "idle") : "";
  var isZoomed = false;
  var tipIndex = 0;
  var suppressNextClick = false;
  var currentPos = null;
  var turns = [];
  var chatController = null;
  var chatStreaming = false;

  function isEnglish() {
    if (window.SiteFlowI18n && typeof window.SiteFlowI18n.getLang === "function") {
      return window.SiteFlowI18n.getLang() === "en";
    }
    return document.documentElement.getAttribute("data-lang") === "en";
  }

  function tr(key, zhFallback, enFallback) {
    if (window.SiteFlowI18n && typeof window.SiteFlowI18n.t === "function") {
      var val = window.SiteFlowI18n.t(key);
      if (val && val !== key) return val;
    }
    return isEnglish() ? enFallback : zhFallback;
  }

  function trVars(key, vars, zhFallback, enFallback) {
    if (window.SiteFlowI18n && typeof window.SiteFlowI18n.t === "function") {
      var val = window.SiteFlowI18n.t(key, vars);
      if (val && val !== key) return val;
    }
    var template = isEnglish() ? enFallback : zhFallback;
    return template.replace(/\{([a-zA-Z0-9_]+)\}/g, function (m, k) {
      return vars && vars[k] !== undefined ? String(vars[k]) : m;
    });
  }

  function trText(text) {
    if (!text) return "";
    if (window.SiteFlowI18n && typeof window.SiteFlowI18n.translateText === "function") {
      return window.SiteFlowI18n.translateText(text);
    }
    return text;
  }

  function cloneTemplateIcon(name) {
    var tpl = root.querySelector('template[data-mascot-icon="' + name + '"]');
    if (tpl && tpl.content) {
      return tpl.content.cloneNode(true);
    }
    return document.createDocumentFragment();
  }

  function syncResetButton() {
    if (!chatResetBtn) return;
    chatResetBtn.classList.toggle("has-context", turns.length > 0);
    var label = turns.length > 0
      ? trVars(
        "blog.ext.mascot.chat_reset_ctx_count",
        { n: turns.length },
        "重置上下文（已保留 {n} 轮）",
        "Reset context ({n} turns)"
      )
      : tr("blog.ext.mascot.chat_reset_ctx", "重置对话上下文", "Reset conversation context");
    chatResetBtn.setAttribute("title", label);
    chatResetBtn.setAttribute("aria-label", label);
  }

  function isDockFocused() {
    return Boolean(chatForm && document.activeElement && chatForm.contains(document.activeElement));
  }

  function isUserEngagedWithMascot(ignoreFocus) {
    return stageHovered || bubbleHovered || dockHovered || (!ignoreFocus && isDockFocused()) || chatStreaming;
  }

  function cancelAiFadeTimer() {
    if (aiFadeTimer) {
      clearTimeout(aiFadeTimer);
      aiFadeTimer = null;
    }
  }

  function revealAiBubble() {
    cancelAiFadeTimer();
    if (!bubble || bubbleMode !== "ai" || bubble.hidden) return;
    if (aiBubbleFaded || bubble.classList.contains("is-faded")) {
      bubble.classList.remove("is-faded");
      aiBubbleFaded = false;
      positionBubble();
    }
  }

  function fadeAiBubble() {
    cancelAiFadeTimer();
    if (!bubble || bubbleMode !== "ai" || bubble.hidden || isUserEngagedWithMascot()) return;
    bubble.classList.add("is-faded");
    aiBubbleFaded = true;
  }

  function scheduleAiFade(delay, ignoreFocus) {
    cancelAiFadeTimer();
    if (!bubble || bubbleMode !== "ai" || bubble.hidden || isUserEngagedWithMascot(ignoreFocus)) return;
    var wait = typeof delay === "number" ? delay : AI_READ_FADE_DELAY;
    aiFadeTimer = setTimeout(function () {
      aiFadeTimer = null;
      fadeAiBubble();
    }, wait);
  }

  function clearPendingDockWidth() {
    if (dockWidthTimer) {
      clearTimeout(dockWidthTimer);
      dockWidthTimer = null;
    }
    pendingDockWidth = null;
  }

  function viewportWidth() {
    return document.documentElement.clientWidth || window.innerWidth;
  }

  function viewportHeight() {
    return document.documentElement.clientHeight || window.innerHeight;
  }

  function dockExpectedWidth(forceExpanded) {
    var expanded = typeof forceExpanded === "boolean"
      ? forceExpanded
      : (isDockFocused() || root.classList.contains("is-dock-dirty") || chatStreaming);
    var base = expanded ? DOCK_EXPANDED_WIDTH : DOCK_COMPACT_WIDTH;
    return Math.max(0, Math.min(base, viewportWidth() - 2 * VIEWPORT_MARGIN));
  }

  function computeCenteredShift(centerX, width) {
    var vw = viewportWidth();
    var safeWidth = Math.max(0, width || 0);
    var idealLeft = centerX - safeWidth / 2;
    var clampedLeft;
    if (safeWidth >= vw - 2 * VIEWPORT_MARGIN) {
      clampedLeft = (vw - safeWidth) / 2;
    } else {
      var minLeft = VIEWPORT_MARGIN;
      var maxLeft = vw - VIEWPORT_MARGIN - safeWidth;
      clampedLeft = Math.min(maxLeft, Math.max(minLeft, idealLeft));
    }
    return {
      offsetX: Math.round(clampedLeft - idealLeft),
      clampedLeft: clampedLeft
    };
  }

  function positionDock(targetWidthOverride) {
    if (!chatForm || root.classList.contains("is-collapsed")) return;
    var rect = root.getBoundingClientRect();
    if (!rect.width && !rect.height) return;
    var maxDockWidth = Math.max(0, viewportWidth() - 2 * VIEWPORT_MARGIN);
    var dockWidth = 0;
    if (typeof targetWidthOverride === "number" && isFinite(targetWidthOverride) && targetWidthOverride > 0) {
      dockWidth = Math.min(targetWidthOverride, maxDockWidth);
      clearPendingDockWidth();
      pendingDockWidth = dockWidth;
      dockWidthTimer = setTimeout(function () {
        dockWidthTimer = null;
        pendingDockWidth = null;
        positionDock();
      }, 240);
    } else if (pendingDockWidth !== null) {
      dockWidth = Math.min(pendingDockWidth, maxDockWidth);
    } else {
      dockWidth = chatForm.offsetWidth || dockExpectedWidth();
    }
    if (!dockWidth) return;
    var centerX = rect.left + rect.width / 2;
    var shifted = computeCenteredShift(centerX, dockWidth);
    chatForm.style.setProperty("--sf-dock-shift", shifted.offsetX + "px");
  }

  function cancelDockTimer() {
    if (dockHideTimer) {
      clearTimeout(dockHideTimer);
      dockHideTimer = null;
    }
  }

  function openDock() {
    if (!chatForm || root.classList.contains("is-collapsed")) return;
    cancelDockTimer();
    root.classList.add("is-dock-open");
    positionDock();
  }

  function syncDockDirty() {
    if (!chatForm) return;
    var dirty = Boolean(chatInput && chatInput.value.trim());
    var wasDirty = root.classList.contains("is-dock-dirty");
    root.classList.toggle("is-dock-dirty", dirty);
    if (dirty !== wasDirty) {
      positionDock(dockExpectedWidth());
    } else {
      positionDock();
    }
  }

  function scheduleDockClose(delay) {
    if (!chatForm) return;
    cancelDockTimer();
    var wait = typeof delay === "number" ? delay : 280;
    dockHideTimer = setTimeout(function () {
      dockHideTimer = null;
      if (stageHovered || dockHovered || isDockFocused() || chatStreaming) return;
      root.classList.remove("is-dock-open");
    }, wait);
  }

  function clampPosition(x, y) {
    var width = root.offsetWidth || 84;
    var height = root.offsetHeight || 108;
    var extraBottom = (chatForm && !root.classList.contains("is-collapsed")) ? 54 : 0;
    var maxX = Math.max(VIEWPORT_MARGIN, viewportWidth() - width - VIEWPORT_MARGIN);
    var maxY = Math.max(VIEWPORT_MARGIN, viewportHeight() - height - extraBottom - VIEWPORT_MARGIN);
    return {
      x: Math.min(maxX, Math.max(VIEWPORT_MARGIN, Math.round(x))),
      y: Math.min(maxY, Math.max(VIEWPORT_MARGIN, Math.round(y)))
    };
  }

  function applyCustomPosition(x, y) {
    var clamped = clampPosition(x, y);
    currentPos = clamped;
    root.classList.add("is-positioned");
    root.style.left = clamped.x + "px";
    root.style.top = clamped.y + "px";
    positionBubble();
    positionDock();
  }

  function positionBubble() {
    if (!bubble) return;
    var rect = root.getBoundingClientRect();
    var vh = viewportHeight();
    var spaceAbove = rect.top - VIEWPORT_MARGIN;
    var spaceBelow = vh - rect.bottom - VIEWPORT_MARGIN;
    var showBelow = false;
    if (bubbleMode === "ai") {
      showBelow = spaceAbove < 180 && spaceBelow > spaceAbove;
      if (bubbleBody) {
        var avail = (showBelow ? spaceBelow : spaceAbove) - 34;
        var targetMax = Math.min(320, Math.floor(vh * 0.46));
        if (avail > 0 && avail < targetMax) {
          bubbleBody.style.maxHeight = Math.max(120, Math.floor(avail)) + "px";
        } else {
          bubbleBody.style.maxHeight = "";
        }
      }
    } else {
      if (bubbleBody) bubbleBody.style.maxHeight = "";
      showBelow = spaceAbove < 96 && spaceBelow > spaceAbove;
    }

    bubble.classList.toggle("bubble-below", showBelow);
    if (bubble.hidden) return;

    var bubbleWidth = bubble.offsetWidth;
    if (!bubbleWidth) return;
    var centerX = rect.left + rect.width / 2;
    var shifted = computeCenteredShift(centerX, bubbleWidth);
    var arrowPad = Math.min(18, Math.floor(bubbleWidth / 2));
    var arrowX = Math.max(arrowPad, Math.min(bubbleWidth - arrowPad, Math.round(centerX - shifted.clampedLeft)));
    bubble.style.setProperty("--sf-bubble-shift", shifted.offsetX + "px");
    bubble.style.setProperty("--sf-bubble-arrow-x", arrowX + "px");
  }

  function cancelTipTimer() {
    if (hideTimer) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  }

  function scheduleTipHide(delay) {
    cancelTipTimer();
    if (bubbleMode !== "tip" || bubbleHovered) return;
    hideTimer = setTimeout(function () {
      hideTimer = null;
      if (bubbleMode === "tip" && !bubbleHovered && bubble) {
        bubble.hidden = true;
        bubbleMode = "none";
      }
    }, delay || 5000);
  }

  function cancelSpeakBurst() {
    if (speakBurstTimer) {
      clearTimeout(speakBurstTimer);
      speakBurstTimer = null;
    }
  }

  function clearPoseSwap() {
    if (poseSwapTimer) {
      clearTimeout(poseSwapTimer);
      poseSwapTimer = null;
    }
    if (poseImg) poseImg.classList.remove("is-pose-swapping");
  }

  function syncPose() {
    if (!poseImg || !config.poses.idle) return;
    var desiredPose = "idle";
    if (mascotAction === "tap" && config.poses.tap && !chatStreaming) {
      desiredPose = "tap";
    } else if (config.poses[mascotMood]) {
      desiredPose = mascotMood;
    }
    if (desiredPose === currentPose) return;
    currentPose = desiredPose;
    poseImg.setAttribute("data-mascot-pose", desiredPose);
    poseImg.src = config.poses[desiredPose];
    clearPoseSwap();
    void poseImg.offsetWidth;
    poseImg.classList.add("is-pose-swapping");
    poseSwapTimer = setTimeout(clearPoseSwap, 280);
  }

  function clearTapAction(skipSync) {
    if (tapPoseTimer) {
      clearTimeout(tapPoseTimer);
      tapPoseTimer = null;
    }
    mascotAction = "";
    root.classList.remove("is-tapping");
    root.setAttribute("data-mascot-action", "none");
    if (!skipSync) syncPose();
  }

  function triggerTapAction(ms) {
    if (chatStreaming || !hasPoseTap) return;
    cancelSpeakBurst();
    if (mascotMood !== "idle") {
      mascotMood = "idle";
      root.classList.remove("is-thinking", "is-speaking");
      root.setAttribute("data-mascot-mood", "idle");
    }
    if (tapPoseTimer) {
      clearTimeout(tapPoseTimer);
      tapPoseTimer = null;
    }
    mascotAction = "tap";
    root.classList.add("is-tapping");
    root.setAttribute("data-mascot-action", "tap");
    syncPose();
    tapPoseTimer = setTimeout(function () {
      tapPoseTimer = null;
      if (!chatStreaming) {
        clearTapAction();
      }
    }, ms || 1200);
  }

  function setMascotMood(nextMood) {
    var normalized = (nextMood === "thinking" || nextMood === "speaking") ? nextMood : "idle";
    mascotMood = normalized;
    root.classList.toggle("is-thinking", normalized === "thinking");
    root.classList.toggle("is-speaking", normalized === "speaking");
    root.setAttribute("data-mascot-mood", normalized);
    syncPose();
  }

  function triggerSpeakingBurst(ms) {
    if (chatStreaming) return;
    cancelSpeakBurst();
    clearTapAction(true);
    setMascotMood("speaking");
    speakBurstTimer = setTimeout(function () {
      speakBurstTimer = null;
      if (!chatStreaming) {
        setMascotMood("idle");
      }
    }, ms || 1350);
  }

  function clearBounce() {
    if (bounceTimer) {
      clearTimeout(bounceTimer);
      bounceTimer = null;
    }
    root.classList.remove("is-bouncing");
  }

  function syncZoomButton() {
    if (!zoomBtn) return;
    var key = isZoomed ? "blog.ext.mascot.zoom_out" : "blog.ext.mascot.zoom_in";
    var label = isZoomed
      ? tr("blog.ext.mascot.zoom_out", "缩小看板娘", "Shrink mascot")
      : tr("blog.ext.mascot.zoom_in", "放大看板娘", "Enlarge mascot");
    zoomBtn.setAttribute("aria-pressed", isZoomed ? "true" : "false");
    zoomBtn.setAttribute("data-i18n-title", key);
    zoomBtn.setAttribute("data-i18n-aria-label", key);
    zoomBtn.setAttribute("title", label);
    zoomBtn.setAttribute("aria-label", label);
    if (zoomInIcon) zoomInIcon.hidden = isZoomed;
    if (zoomOutIcon) zoomOutIcon.hidden = !isZoomed;
  }

  function applyZoom(zoomed, persist) {
    isZoomed = Boolean(zoomed);
    root.classList.toggle("is-zoomed", isZoomed);
    syncZoomButton();
    if (persist !== false) {
      try {
        localStorage.setItem(ZOOM_KEY, isZoomed ? "1" : "0");
      } catch (e) {}
    }
    positionBubble();
    positionDock();
    if (zoomClampTimer) {
      clearTimeout(zoomClampTimer);
      zoomClampTimer = null;
    }
    zoomClampTimer = setTimeout(function () {
      zoomClampTimer = null;
      if (currentPos && root.classList.contains("is-positioned")) {
        applyCustomPosition(currentPos.x, currentPos.y);
      } else {
        positionBubble();
        positionDock();
      }
    }, 320);
  }

  function showTipMessage(text, duration, opts) {
    if (!bubble || !bubbleBody || !text) return;
    if (chatStreaming) return;
    var skipSpeak = opts === true || Boolean(opts && opts.skipSpeakBurst);
    cancelTipTimer();
    cancelAiFadeTimer();
    aiBubbleFaded = false;
    bubble.classList.remove("is-faded");
    bubbleMode = "tip";
    bubble.classList.remove("is-rich");
    bubbleBody.textContent = "";
    var span = document.createElement("span");
    span.setAttribute("data-mascot-text", "");
    span.textContent = text;
    bubbleBody.appendChild(span);
    bubble.hidden = false;
    positionBubble();
    if (!skipSpeak) triggerSpeakingBurst(1350);
    scheduleTipHide(duration || 5000);
  }

  function hideBubble() {
    cancelTipTimer();
    cancelAiFadeTimer();
    aiBubbleFaded = false;
    bubbleMode = "none";
    if (bubble) {
      bubble.classList.remove("is-faded");
      bubble.classList.remove("is-rich");
      bubble.hidden = true;
    }
  }

  function applyCollapsed(collapsed) {
    root.classList.toggle("is-collapsed", collapsed);
    if (expandBtn) expandBtn.hidden = !collapsed;
    if (collapseBtn) collapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    if (collapsed) {
      cancelDockTimer();
      clearPendingDockWidth();
      stageHovered = false;
      bubbleHovered = false;
      dockHovered = false;
      root.classList.remove("is-dock-open");
      if (!chatStreaming) {
        cancelSpeakBurst();
        clearTapAction(true);
        setMascotMood("idle");
      }
      hideBubble();
    }
    if (currentPos) {
      var clamped = clampPosition(currentPos.x, currentPos.y);
      currentPos = clamped;
      root.style.left = clamped.x + "px";
      root.style.top = clamped.y + "px";
    }
    if (!collapsed) {
      positionBubble();
      positionDock();
    }
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch (e) {}
  }

  function readingPercent() {
    var doc = document.documentElement;
    var scrollable = doc.scrollHeight - viewportHeight();
    if (scrollable <= 120) return null;
    var pct = Math.round((window.scrollY / scrollable) * 100);
    return Math.max(0, Math.min(100, pct));
  }

  function activeHeadingText() {
    var tocActive = document.querySelector(".toc-link.is-active");
    if (tocActive) {
      var tocTxt = (tocActive.textContent || "").trim();
      if (tocTxt) return tocTxt;
    }
    var postBody = document.querySelector(".post-body, main.resume");
    if (!postBody) return null;
    var headings = postBody.querySelectorAll("h1, h2, h3");
    if (!headings.length) return null;
    var mid = viewportHeight() * 0.5;
    var candidate = "";
    for (var i = 0; i < headings.length; i += 1) {
      var rect = headings[i].getBoundingClientRect();
      if (rect.top <= mid) {
        var txt = (headings[i].textContent || "").trim();
        if (txt) candidate = txt;
      }
    }
    return candidate || null;
  }

  function timeOfDayWord() {
    var h = new Date().getHours();
    if (isEnglish()) {
      if (h < 12) return "Morning";
      if (h < 18) return "Afternoon";
      return "Evening";
    }
    if (h < 6) return "凌晨";
    if (h < 9) return "早上";
    if (h < 12) return "上午";
    if (h < 14) return "中午";
    if (h < 18) return "下午";
    return "晚上";
  }

  function resolveTipTemplate(rawLine) {
    if (typeof rawLine !== "string") return null;
    var trimmed = rawLine.trim();
    if (!trimmed || trimmed.charAt(0) === "#") return null;
    var unavailable = false;
    var resolved = trimmed.replace(TIP_TOKEN_RE, function (_match, token) {
      if (token === "progress") {
        var pct = readingPercent();
        if (pct === null) {
          unavailable = true;
          return "";
        }
        return String(pct);
      }
      if (token === "heading") {
        var heading = activeHeadingText();
        if (!heading) {
          unavailable = true;
          return "";
        }
        return heading;
      }
      if (token === "title") {
        var title = (config.post_title || config.project_title || document.title || "").trim();
        if (!title) {
          unavailable = true;
          return "";
        }
        return title;
      }
      if (token === "site") {
        var site = (config.project_title || document.title || "").trim();
        if (!site) {
          unavailable = true;
          return "";
        }
        return site;
      }
      if (token === "words") {
        if (!(config.post_words > 0)) {
          unavailable = true;
          return "";
        }
        return String(config.post_words);
      }
      if (token === "time") {
        return timeOfDayWord();
      }
      return "";
    });
    if (unavailable || !resolved.trim()) return null;
    return resolved;
  }

  function nextLine() {
    var total = config.tips.length;
    for (var step = 0; step < total; step += 1) {
      var idx = (tipIndex + step) % total;
      var resolved = resolveTipTemplate(config.tips[idx]);
      if (resolved) {
        tipIndex = (idx + 1) % total;
        return resolved;
      }
    }
    return resolveTipTemplate(config.greeting) || config.greeting;
  }

  function isSafeHttpUrl(raw) {
    if (!raw || typeof raw !== "string") return false;
    var cleaned = raw.trim();
    if (/[\x00-\x20\x7f]/.test(cleaned)) return false;
    return cleaned.indexOf("https://") === 0 || cleaned.indexOf("http://") === 0;
  }

  function appendInlineMarkdown(parent, text, depth) {
    var lvl = depth || 0;
    var pos = 0;
    var len = text.length;
    var plain = "";

    function flushPlain() {
      if (plain) {
        parent.appendChild(document.createTextNode(plain));
        plain = "";
      }
    }

    while (pos < len) {
      var ch = text.charAt(pos);

      if (ch === "`") {
        var endCode = text.indexOf("`", pos + 1);
        if (endCode > pos + 1) {
          flushPlain();
          var codeEl = document.createElement("code");
          codeEl.textContent = text.slice(pos + 1, endCode);
          parent.appendChild(codeEl);
          pos = endCode + 1;
          continue;
        }
      }

      if (ch === "[") {
        var closeBracket = text.indexOf("]", pos + 1);
        if (closeBracket > pos + 1 && text.charAt(closeBracket + 1) === "(") {
          var depthParen = 0;
          var closeParen = -1;
          for (var pIdx = closeBracket + 2; pIdx < len; pIdx += 1) {
            var pc = text.charAt(pIdx);
            if (pc === "\n") break;
            if (pc === "(") {
              depthParen += 1;
            } else if (pc === ")") {
              if (depthParen === 0) {
                closeParen = pIdx;
                break;
              }
              depthParen -= 1;
            }
          }
          if (closeParen > closeBracket + 2) {
            var linkLabel = text.slice(pos + 1, closeBracket);
            var linkUrl = text.slice(closeBracket + 2, closeParen).trim();
            if (linkLabel.indexOf("\n") === -1 && linkUrl.indexOf("\n") === -1) {
              flushPlain();
              if (isSafeHttpUrl(linkUrl)) {
                var aEl = document.createElement("a");
                aEl.href = linkUrl;
                aEl.target = "_blank";
                aEl.rel = "noopener noreferrer";
                if (lvl < 4) appendInlineMarkdown(aEl, linkLabel, lvl + 1);
                else aEl.textContent = linkLabel;
                parent.appendChild(aEl);
              } else {
                parent.appendChild(document.createTextNode(linkLabel));
              }
              pos = closeParen + 1;
              continue;
            }
          }
        }
      }

      if (ch === "*" && text.charAt(pos + 1) === "*" && lvl < 4) {
        var endBold = text.indexOf("**", pos + 2);
        if (endBold > pos + 2) {
          var boldInner = text.slice(pos + 2, endBold);
          if (boldInner.trim()) {
            flushPlain();
            var strongEl = document.createElement("strong");
            appendInlineMarkdown(strongEl, boldInner, lvl + 1);
            parent.appendChild(strongEl);
            pos = endBold + 2;
            continue;
          }
        }
      }

      if (ch === "*" && text.charAt(pos + 1) !== "*" && text.charAt(pos + 1) !== " " && lvl < 4) {
        var searchIdx = pos + 1;
        var endEm = -1;
        while (searchIdx < len) {
          var cand = text.indexOf("*", searchIdx);
          if (cand === -1) break;
          if (text.charAt(cand + 1) === "*") {
            searchIdx = cand + 2;
            continue;
          }
          if (cand > pos + 1 && text.charAt(cand - 1) !== " ") {
            endEm = cand;
            break;
          }
          searchIdx = cand + 1;
        }
        if (endEm > pos + 1) {
          flushPlain();
          var emEl = document.createElement("em");
          appendInlineMarkdown(emEl, text.slice(pos + 1, endEm), lvl + 1);
          parent.appendChild(emEl);
          pos = endEm + 1;
          continue;
        }
      }

      plain += ch;
      pos += 1;
    }

    flushPlain();
  }

  function renderMarkdownToDom(container, markdownText) {
    if (!container) return;
    container.textContent = "";
    if (!markdownText) return;

    var normalized = String(markdownText).replace(/\r\n?/g, "\n");
    var lines = normalized.split("\n");
    var frag = document.createDocumentFragment();
    var i = 0;

    function isBlockStarter(ln) {
      if (/^```/.test(ln)) return true;
      if (/^#{1,6}\s+/.test(ln)) return true;
      if (/^\s*>\s?/.test(ln)) return true;
      if (/^\s*[-*+]\s+/.test(ln)) return true;
      if (/^\s*\d+\.\s+/.test(ln)) return true;
      if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(ln)) return true;
      return false;
    }

    while (i < lines.length) {
      var line = lines[i];

      if (!line.trim()) {
        i += 1;
        continue;
      }

      var fenceMatch = line.match(/^```([A-Za-z0-9_+-]*)\s*$/);
      if (fenceMatch) {
        i += 1;
        var codeLines = [];
        while (i < lines.length && !/^```\s*$/.test(lines[i])) {
          codeLines.push(lines[i]);
          i += 1;
        }
        if (i < lines.length && /^```\s*$/.test(lines[i])) i += 1;
        var preEl = document.createElement("pre");
        preEl.className = "sf-md-pre";
        var codeEl = document.createElement("code");
        codeEl.className = "sf-md-code";
        if (fenceMatch[1]) codeEl.dataset.lang = fenceMatch[1].toLowerCase();
        codeEl.textContent = codeLines.join("\n");
        preEl.appendChild(codeEl);
        frag.appendChild(preEl);
        continue;
      }

      var headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
      if (headingMatch) {
        var hLevel = Math.min(4, headingMatch[1].length);
        var hEl = document.createElement("div");
        hEl.className = "sf-md-h sf-md-h-" + hLevel;
        appendInlineMarkdown(hEl, headingMatch[2].trim(), 0);
        frag.appendChild(hEl);
        i += 1;
        continue;
      }

      if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
        var hrEl = document.createElement("hr");
        hrEl.className = "sf-md-hr";
        frag.appendChild(hrEl);
        i += 1;
        continue;
      }

      if (/^\s*>\s?/.test(line)) {
        var quoteEl = document.createElement("blockquote");
        var quoteLines = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
          i += 1;
        }
        for (var q = 0; q < quoteLines.length; q += 1) {
          if (q > 0) quoteEl.appendChild(document.createElement("br"));
          appendInlineMarkdown(quoteEl, quoteLines[q], 0);
        }
        frag.appendChild(quoteEl);
        continue;
      }

      if (/^\s*[-*+]\s+/.test(line)) {
        var ulEl = document.createElement("ul");
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          var ulItem = document.createElement("li");
          appendInlineMarkdown(ulItem, lines[i].replace(/^\s*[-*+]\s+/, ""), 0);
          ulEl.appendChild(ulItem);
          i += 1;
        }
        frag.appendChild(ulEl);
        continue;
      }

      if (/^\s*\d+\.\s+/.test(line)) {
        var olEl = document.createElement("ol");
        while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
          var olItem = document.createElement("li");
          appendInlineMarkdown(olItem, lines[i].replace(/^\s*\d+\.\s+/, ""), 0);
          olEl.appendChild(olItem);
          i += 1;
        }
        frag.appendChild(olEl);
        continue;
      }

      var paraLines = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !isBlockStarter(lines[i])) {
        paraLines.push(lines[i]);
        i += 1;
      }
      var pEl = document.createElement("p");
      for (var p = 0; p < paraLines.length; p += 1) {
        if (p > 0) pEl.appendChild(document.createElement("br"));
        appendInlineMarkdown(pEl, paraLines[p], 0);
      }
      frag.appendChild(pEl);
    }

    container.appendChild(frag);
  }

  function isNearBottom() {
    if (!bubbleBody) return true;
    return (bubbleBody.scrollHeight - bubbleBody.scrollTop - bubbleBody.clientHeight) < 48;
  }

  function scrollBubbleToBottom() {
    if (!bubbleBody) return;
    bubbleBody.scrollTop = bubbleBody.scrollHeight;
  }

  function createThinkingDetails(thinkingText, isDone) {
    var details = document.createElement("details");
    details.className = "sf-mascot-thinking" + (isDone ? " is-done" : "");
    details.open = !isDone;

    var summary = document.createElement("summary");
    summary.className = "sf-mascot-thinking-summary";

    var ico = document.createElement("span");
    ico.className = "sf-mascot-thinking-ico";
    ico.appendChild(cloneTemplateIcon("brain"));
    summary.appendChild(ico);

    var label = document.createElement("span");
    label.className = "sf-mascot-thinking-label";
    label.textContent = isDone
      ? tr("blog.ext.mascot.thinking_done", "思考过程（点击展开）", "Thought process (click to expand)")
      : tr("blog.ext.mascot.thinking_active", "思考中…", "Thinking...");
    summary.appendChild(label);

    var chev = document.createElement("span");
    chev.className = "sf-mascot-thinking-chev";
    chev.appendChild(cloneTemplateIcon("chevron-right"));
    summary.appendChild(chev);

    var body = document.createElement("div");
    body.className = "sf-mascot-thinking-body";
    body.textContent = thinkingText || "";

    details.appendChild(summary);
    details.appendChild(body);
    return {
      details: details,
      label: label,
      body: body
    };
  }

  function setStreamingState(active) {
    chatStreaming = active;
    root.classList.toggle("is-streaming", active);
    cancelSpeakBurst();
    if (active) {
      clearTapAction(true);
    }
    setMascotMood(active ? "thinking" : "idle");
    if (chatSendBtn) {
      chatSendBtn.hidden = active;
      chatSendBtn.disabled = active;
    }
    if (chatStopBtn) chatStopBtn.hidden = !active;
    if (chatInput) chatInput.disabled = active;
    positionDock(dockExpectedWidth(active ? true : undefined));
    if (!active) scheduleDockClose();
  }

  function fallbackErrorForStatus(statusCode) {
    if (statusCode === 429) {
      return isEnglish() ? "Too many requests, please retry shortly." : "对话请求过于频繁，请稍后再试。";
    }
    if (statusCode === 401) {
      return isEnglish() ? "Project password unlock required." : "需要解锁项目密码后才能对话。";
    }
    if (statusCode === 403) {
      return isEnglish() ? "AI chat is not permitted for your account." : "当前无权限使用 AI 对话。";
    }
    if (statusCode === 503) {
      return isEnglish() ? "AI chat is not configured yet." : "AI 对话尚未配置可用密钥。";
    }
    return isEnglish() ? "Request failed, please try again later." : "请求失败，请稍后重试。";
  }

  function resizeChatInput() {
    if (!chatInput) return;
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 88) + "px";
  }

  function buildPayloadMessages(newUserText) {
    var list = [];
    for (var i = 0; i < turns.length; i += 1) {
      if (turns[i].user && turns[i].content) {
        var assistantMsg = turns[i].content.trim();
        if (assistantMsg.length > MAX_HISTORY_ASSISTANT_CHARS) {
          assistantMsg = assistantMsg.slice(0, MAX_HISTORY_ASSISTANT_CHARS);
        }
        list.push({ role: "user", content: turns[i].user });
        list.push({ role: "assistant", content: assistantMsg });
      }
    }
    list.push({ role: "user", content: newUserText });
    if (list.length > 10) {
      list = list.slice(-10);
      if (list[0].role === "assistant") {
        list = list.slice(1);
      }
    }
    return list;
  }

  function submitChat() {
    if (!config.chat_enabled || !config.chat_url || !chatInput || !bubble || !bubbleBody || chatStreaming) return;
    var content = chatInput.value.trim();
    if (!content) return;
    chatInput.value = "";
    resizeChatInput();
    syncDockDirty();

    cancelTipTimer();
    cancelAiFadeTimer();
    aiBubbleFaded = false;
    bubble.classList.remove("is-faded");
    bubbleMode = "ai";
    bubble.classList.add("is-rich");
    bubbleBody.textContent = "";

    var toolEl = document.createElement("span");
    toolEl.className = "sf-mascot-tool-inline";
    toolEl.hidden = true;
    bubbleBody.appendChild(toolEl);

    var pendingEl = document.createElement("span");
    pendingEl.className = "sf-mascot-bubble-pending";
    pendingEl.textContent = "...";
    bubbleBody.appendChild(pendingEl);

    var mdEl = document.createElement("div");
    mdEl.className = "sf-mascot-md";
    bubbleBody.appendChild(mdEl);

    var errEl = document.createElement("div");
    errEl.className = "sf-mascot-error-inline";
    errEl.setAttribute("role", "alert");
    errEl.hidden = true;
    bubbleBody.appendChild(errEl);

    bubble.hidden = false;
    positionBubble();

    var payloadMessages = buildPayloadMessages(content);
    var turn = {
      user: content,
      thinking: "",
      content: "",
      thinkingAutoCollapsed: false,
      resetAborted: false
    };
    turns.push(turn);
    if (turns.length > 20) {
      turns = turns.slice(-20);
    }

    var thinkingRef = null;
    chatController = new AbortController();
    setStreamingState(true);

    function showInlineError(msg) {
      pendingEl.hidden = true;
      toolEl.hidden = true;
      errEl.textContent = trText(msg);
      errEl.hidden = false;
      positionBubble();
      scrollBubbleToBottom();
    }

    fetch(config.chat_url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
      },
      body: JSON.stringify({
        messages: payloadMessages,
        post_slug: config.post_slug || ""
      }),
      signal: chatController.signal
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().catch(function () { return null; }).then(function (data) {
          var errMsg = (data && (data.error || data.detail)) || fallbackErrorForStatus(resp.status);
          throw new Error(String(errMsg));
        });
      }
      if (!resp.body || !resp.body.getReader) {
        throw new Error(isEnglish() ? "Streaming is not supported in this browser." : "当前浏览器不支持流式响应。");
      }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";
      var doneStreaming = false;

      function handleEvent(evt) {
        if (!evt || typeof evt !== "object" || turn.resetAborted) return;
        if (typeof evt.error === "string" && evt.error) {
          showInlineError(evt.error);
          return;
        }
        if (typeof evt.tool === "string" && evt.tool) {
          if (evt.status === "running") {
            setMascotMood("thinking");
            toolEl.textContent = trText(evt.label) || tr("blog.ext.mascot.tool_running", "正在调用工具…", "Running tool...");
            toolEl.hidden = false;
          } else {
            toolEl.textContent = "";
            toolEl.hidden = true;
          }
        }
        if (typeof evt.thinking === "string" && evt.thinking) {
          var shouldScrollThink = isNearBottom();
          setMascotMood("thinking");
          pendingEl.hidden = true;
          turn.thinking += evt.thinking;
          if (!thinkingRef) {
            thinkingRef = createThinkingDetails(turn.thinking, false);
            bubbleBody.insertBefore(thinkingRef.details, mdEl);
          } else {
            thinkingRef.body.textContent = turn.thinking;
          }
          if (shouldScrollThink) scrollBubbleToBottom();
        }
        if (typeof evt.delta === "string" && evt.delta) {
          var shouldScrollDelta = isNearBottom();
          setMascotMood("speaking");
          pendingEl.hidden = true;
          toolEl.textContent = "";
          toolEl.hidden = true;
          if (!turn.thinkingAutoCollapsed) {
            turn.thinkingAutoCollapsed = true;
            if (thinkingRef) {
              thinkingRef.details.open = false;
              thinkingRef.details.classList.add("is-done");
              thinkingRef.label.textContent = tr(
                "blog.ext.mascot.thinking_done",
                "思考过程（点击展开）",
                "Thought process (click to expand)"
              );
            }
          }
          turn.content += evt.delta;
          renderMarkdownToDom(mdEl, turn.content);
          positionBubble();
          if (shouldScrollDelta) scrollBubbleToBottom();
        }
      }

      function processLines(chunkText) {
        buffer += chunkText;
        var lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (var i = 0; i < lines.length; i += 1) {
          var line = lines[i].trim();
          if (!line || line.indexOf("data:") !== 0) continue;
          var raw = line.slice(5).trim();
          if (!raw) continue;
          if (raw === "[DONE]") {
            doneStreaming = true;
            return;
          }
          try {
            handleEvent(JSON.parse(raw));
          } catch (err) {}
        }
      }

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) {
            var tail = decoder.decode();
            if (tail) processLines(tail);
            if (buffer.trim()) processLines("\n");
            return;
          }
          processLines(decoder.decode(result.value, { stream: true }));
          if (doneStreaming) {
            return reader.cancel().catch(function () {});
          }
          return pump();
        });
      }

      return pump();
    }).catch(function (err) {
      if (err && err.name === "AbortError") {
        return;
      }
      var msg = (err && err.message) ? err.message : (isEnglish() ? "Network error, please retry." : "网络连接失败，请稍后重试。");
      showInlineError(msg);
    }).then(function () {
      pendingEl.hidden = true;
      toolEl.textContent = "";
      toolEl.hidden = true;
      if (thinkingRef && !turn.thinkingAutoCollapsed) {
        turn.thinkingAutoCollapsed = true;
        thinkingRef.details.classList.add("is-done");
        thinkingRef.label.textContent = tr(
          "blog.ext.mascot.thinking_done",
          "思考过程（点击展开）",
          "Thought process (click to expand)"
        );
      }
      if (!turn.content || !turn.content.trim()) {
        var tIdx = turns.indexOf(turn);
        if (tIdx !== -1) turns.splice(tIdx, 1);
      }
      chatController = null;
      setStreamingState(false);
      syncResetButton();
      if (!turn.resetAborted) {
        positionBubble();
        positionDock();
        scheduleAiFade(AI_READ_FADE_DELAY);
      }
    });
  }

  clearTapAction(true);
  setMascotMood("idle");

  if (poseImg) {
    poseImg.addEventListener("animationend", function (e) {
      if (e.animationName === "sfMascotPoseIn") {
        clearPoseSwap();
      }
    });
  }

  var savedCollapsed = false;
  try {
    savedCollapsed = localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch (e) {}
  applyCollapsed(savedCollapsed);

  var savedZoomed = false;
  try {
    savedZoomed = localStorage.getItem(ZOOM_KEY) === "1";
  } catch (e) {}
  applyZoom(savedZoomed, false);

  if (config.draggable) {
    try {
      var rawPos = localStorage.getItem(POS_KEY);
      if (rawPos) {
        var parsedPos = JSON.parse(rawPos);
        if (
          parsedPos &&
          typeof parsedPos.x === "number" &&
          typeof parsedPos.y === "number" &&
          isFinite(parsedPos.x) &&
          isFinite(parsedPos.y)
        ) {
          applyCustomPosition(parsedPos.x, parsedPos.y);
        }
      }
    } catch (e) {}
  }

  syncResetButton();
  syncDockDirty();
  positionBubble();
  positionDock();

  if (typeof ResizeObserver === "function") {
    var mascotResizeObserver = new ResizeObserver(function (entries) {
      for (var idx = 0; idx < entries.length; idx += 1) {
        var target = entries[idx].target;
        if (target === bubble) {
          positionBubble();
        } else if (target === chatForm) {
          positionDock();
        } else if (target === root) {
          positionBubble();
          positionDock();
        }
      }
    });
    if (bubble) mascotResizeObserver.observe(bubble);
    if (chatForm) mascotResizeObserver.observe(chatForm);
    mascotResizeObserver.observe(root);
  }

  if (!savedCollapsed && config.greeting) {
    var greeted = false;
    try {
      greeted = sessionStorage.getItem(GREET_KEY) === "1";
      sessionStorage.setItem(GREET_KEY, "1");
    } catch (e) {}
    if (!greeted) {
      showTipMessage(resolveTipTemplate(config.greeting) || config.greeting, 5000, true);
    }
  }

  if (bubble) {
    bubble.addEventListener("mouseenter", function () {
      bubbleHovered = true;
      cancelTipTimer();
      if (bubbleMode === "ai" && !bubble.hidden) {
        revealAiBubble();
      }
    });
    bubble.addEventListener("mouseleave", function () {
      bubbleHovered = false;
      if (bubbleMode === "tip" && !bubble.hidden) {
        scheduleTipHide(2600);
      } else if (bubbleMode === "ai" && !bubble.hidden && !isUserEngagedWithMascot()) {
        scheduleAiFade(AI_LEAVE_FADE_DELAY);
      }
    });
    bubble.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !bubble.hidden) {
        hideBubble();
        if (chatInput) chatInput.focus();
      }
    });
  }

  if (bubbleBody) {
    bubbleBody.addEventListener("scroll", function () {
      if (bubble && bubbleMode === "ai" && !bubble.hidden) {
        revealAiBubble();
        if (!isUserEngagedWithMascot()) {
          scheduleAiFade(AI_READ_FADE_DELAY);
        }
      }
    }, { passive: true });
  }

  if (config.draggable) {
    var dragHandles = root.querySelectorAll("[data-mascot-drag-handle]");
    var dragState = null;

    var onPointerDown = function (e) {
      if (!e.isPrimary) return;
      if (e.pointerType === "mouse" && e.button !== 0) return;
      var rect = root.getBoundingClientRect();
      dragState = {
        pointerId: e.pointerId,
        handle: e.currentTarget,
        startX: e.clientX,
        startY: e.clientY,
        originLeft: rect.left,
        originTop: rect.top,
        moved: false
      };
    };

    var onPointerMove = function (e) {
      if (!dragState || e.pointerId !== dragState.pointerId) return;
      var dx = e.clientX - dragState.startX;
      var dy = e.clientY - dragState.startY;
      if (!dragState.moved) {
        if (Math.hypot(dx, dy) <= DRAG_THRESHOLD) return;
        dragState.moved = true;
        try {
          dragState.handle.setPointerCapture(e.pointerId);
        } catch (err) {}
        root.classList.add("is-dragging");
        if (bubble && bubbleMode === "tip") {
          hideBubble();
        }
      }
      applyCustomPosition(dragState.originLeft + dx, dragState.originTop + dy);
    };

    var finishDrag = function (e) {
      if (!dragState || e.pointerId !== dragState.pointerId) return;
      var state = dragState;
      dragState = null;
      try {
        if (state.handle.hasPointerCapture && state.handle.hasPointerCapture(e.pointerId)) {
          state.handle.releasePointerCapture(e.pointerId);
        }
      } catch (err) {}
      root.classList.remove("is-dragging");
      if (state.moved) {
        suppressNextClick = true;
        setTimeout(function () {
          suppressNextClick = false;
        }, 50);
        if (currentPos) {
          try {
            localStorage.setItem(POS_KEY, JSON.stringify(currentPos));
          } catch (err) {}
        }
        positionBubble();
        positionDock();
      }
    };

    for (var h = 0; h < dragHandles.length; h += 1) {
      dragHandles[h].addEventListener("pointerdown", onPointerDown);
      dragHandles[h].addEventListener("pointermove", onPointerMove);
      dragHandles[h].addEventListener("pointerup", finishDrag);
      dragHandles[h].addEventListener("pointercancel", finishDrag);
    }
  }

  window.addEventListener("resize", function () {
    if (currentPos && root.classList.contains("is-positioned")) {
      applyCustomPosition(currentPos.x, currentPos.y);
    } else {
      positionBubble();
      positionDock();
    }
  });

  if (trigger) {
    trigger.addEventListener("animationend", function (e) {
      if (e.animationName === "sfMascotBounce") {
        clearBounce();
      }
    });
    trigger.addEventListener("click", function () {
      if (suppressNextClick) {
        suppressNextClick = false;
        return;
      }
      clearBounce();
      void root.offsetWidth;
      root.classList.add("is-bouncing");
      bounceTimer = setTimeout(clearBounce, 640);
      if (!chatStreaming) {
        if (hasPoseTap) {
          triggerTapAction(1200);
        }
        showTipMessage(nextLine(), 5000, { skipSpeakBurst: hasPoseTap });
      }
    });
  }

  if (zoomBtn) {
    zoomBtn.addEventListener("click", function () {
      applyZoom(!isZoomed, true);
    });
  }

  if (topBtn) {
    topBtn.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  if (collapseBtn) {
    collapseBtn.addEventListener("click", function () {
      applyCollapsed(true);
    });
  }

  if (expandBtn) {
    expandBtn.addEventListener("click", function () {
      if (suppressNextClick) {
        suppressNextClick = false;
        return;
      }
      applyCollapsed(false);
      if (config.greeting) {
        showTipMessage(resolveTipTemplate(config.greeting) || config.greeting, 4000);
      }
    });
  }

  if (chatResetBtn) {
    chatResetBtn.addEventListener("click", function () {
      if (chatController) {
        if (turns.length > 0) {
          turns[turns.length - 1].resetAborted = true;
        }
        chatController.abort();
        chatController = null;
        setStreamingState(false);
      }
      turns = [];
      syncResetButton();
      syncDockDirty();
      showTipMessage(
        tr("blog.ext.mascot.chat_ctx_cleared", "已重置对话上下文～", "Conversation context cleared."),
        2400
      );
      if (chatInput) chatInput.focus();
    });
  }

  if (chatStopBtn) {
    chatStopBtn.addEventListener("click", function () {
      if (chatController) chatController.abort();
    });
  }

  if (stage) {
    stage.addEventListener("mouseenter", function () {
      stageHovered = true;
      if (chatForm) openDock();
      if (bubble && bubbleMode === "ai" && !bubble.hidden) {
        revealAiBubble();
      }
    });
    stage.addEventListener("mouseleave", function () {
      stageHovered = false;
      if (chatForm) scheduleDockClose();
      if (bubble && bubbleMode === "ai" && !bubble.hidden && !isUserEngagedWithMascot()) {
        scheduleAiFade(AI_LEAVE_FADE_DELAY);
      }
    });
  }

  if (chatForm) {
    chatForm.addEventListener("mouseenter", function () {
      dockHovered = true;
      openDock();
      if (bubble && bubbleMode === "ai" && !bubble.hidden) {
        revealAiBubble();
      }
    });
    chatForm.addEventListener("mouseleave", function () {
      dockHovered = false;
      scheduleDockClose();
      if (bubble && bubbleMode === "ai" && !bubble.hidden && !isUserEngagedWithMascot()) {
        scheduleAiFade(AI_LEAVE_FADE_DELAY);
      }
    });
    chatForm.addEventListener("focusin", function () {
      openDock();
      positionDock(Math.min(DOCK_EXPANDED_WIDTH, viewportWidth() - 2 * VIEWPORT_MARGIN));
      if (bubble && bubbleMode === "ai" && !bubble.hidden) {
        revealAiBubble();
      }
    });
    chatForm.addEventListener("focusout", function (e) {
      if (e.relatedTarget && chatForm.contains(e.relatedTarget)) return;
      scheduleDockClose(stageHovered || dockHovered ? 280 : 0);
      if (!chatStreaming && !root.classList.contains("is-dock-dirty")) {
        positionDock(Math.min(DOCK_COMPACT_WIDTH, viewportWidth() - 2 * VIEWPORT_MARGIN));
      }
      if (bubble && bubbleMode === "ai" && !bubble.hidden && !isUserEngagedWithMascot(true)) {
        scheduleAiFade(AI_LEAVE_FADE_DELAY, true);
      }
    });
    chatForm.addEventListener("transitionend", function (e) {
      if (e.target === chatForm && e.propertyName === "width" && pendingDockWidth !== null) {
        clearPendingDockWidth();
        positionDock();
      }
    });
    chatForm.addEventListener("submit", function (e) {
      e.preventDefault();
      submitChat();
    });
  }

  if (chatInput) {
    chatInput.addEventListener("input", function () {
      resizeChatInput();
      syncDockDirty();
    });
    chatInput.addEventListener("focus", function () {
      if (currentPos && root.classList.contains("is-positioned")) {
        setTimeout(function () {
          if (currentPos) applyCustomPosition(currentPos.x, currentPos.y);
        }, 220);
      }
    });
    chatInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        submitChat();
      } else if (e.key === "Escape" && bubble && !bubble.hidden) {
        hideBubble();
      }
    });
  }

  window.addEventListener("siteflow:langchange", function () {
    syncResetButton();
    syncZoomButton();
    if (bubbleBody) {
      var detailsList = bubbleBody.querySelectorAll(".sf-mascot-thinking");
      for (var d = 0; d < detailsList.length; d += 1) {
        var lbl = detailsList[d].querySelector(".sf-mascot-thinking-label");
        if (!lbl) continue;
        lbl.textContent = detailsList[d].classList.contains("is-done")
          ? tr("blog.ext.mascot.thinking_done", "思考过程（点击展开）", "Thought process (click to expand)")
          : tr("blog.ext.mascot.thinking_active", "思考中…", "Thinking...");
      }
    }
  });
})();
