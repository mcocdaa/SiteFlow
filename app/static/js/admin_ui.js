(function () {
  "use strict";

  var TOAST_STORAGE_KEY = "sf_pending_toast";
  var SUPPORTS_POPOVER =
    typeof HTMLElement !== "undefined" &&
    Object.prototype.hasOwnProperty.call(HTMLElement.prototype, "popover");

  var ICON_SVGS = {
    success:
      '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
    info:
      '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
    error:
      '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>',
    close:
      '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>'
  };

  function t(key, vars, fallback) {
    if (key && window.SiteFlowI18n && window.SiteFlowI18n.t) {
      var val = window.SiteFlowI18n.t(key, vars);
      if (val !== key || !fallback) return val;
    }
    return fallback !== undefined ? fallback : key || "";
  }

  function isPopoverOpen(el) {
    if (!el) return false;
    if (!SUPPORTS_POPOVER) return el.classList.contains("is-open");
    try {
      return el.matches(":popover-open");
    } catch (e) {
      return false;
    }
  }

  function openPopoverTop(el, forcePromote) {
    if (!el) return;
    if (!SUPPORTS_POPOVER) {
      el.classList.add("is-open");
      return;
    }
    var already = isPopoverOpen(el);
    if (already && forcePromote) {
      try {
        el.hidePopover();
      } catch (e) {}
      already = false;
    }
    if (!already) {
      try {
        el.showPopover();
      } catch (e) {}
    }
  }

  function closePopover(el) {
    if (!el) return;
    if (!SUPPORTS_POPOVER) {
      el.classList.remove("is-open");
      return;
    }
    if (isPopoverOpen(el)) {
      try {
        el.hidePopover();
      } catch (e) {}
    }
  }

  var toastRegion = null;
  var politeLive = null;
  var assertiveLive = null;
  var activeToasts = [];

  function ensureToastRegion() {
    if (toastRegion && document.body && document.body.contains(toastRegion)) {
      return toastRegion;
    }
    if (!document.body) return null;

    toastRegion = document.createElement("div");
    toastRegion.className = "sf-toast-region" + (SUPPORTS_POPOVER ? "" : " sf-popover-fallback");
    toastRegion.setAttribute("role", "region");
    toastRegion.setAttribute("aria-label", t("ui.toast_region", null, "通知"));
    toastRegion.setAttribute("data-i18n-aria-label", "ui.toast_region");
    if (SUPPORTS_POPOVER) {
      toastRegion.setAttribute("popover", "manual");
    }
    document.body.appendChild(toastRegion);

    if (!politeLive) {
      politeLive = document.createElement("div");
      politeLive.className = "sf-sr-only";
      politeLive.setAttribute("aria-live", "polite");
      politeLive.setAttribute("aria-atomic", "true");
      document.body.appendChild(politeLive);
    }
    if (!assertiveLive) {
      assertiveLive = document.createElement("div");
      assertiveLive.className = "sf-sr-only";
      assertiveLive.setAttribute("role", "alert");
      assertiveLive.setAttribute("aria-live", "assertive");
      assertiveLive.setAttribute("aria-atomic", "true");
      document.body.appendChild(assertiveLive);
    }

    return toastRegion;
  }

  function announceToast(message, type) {
    if (!message) return;
    if (typeof document.ariaNotify === "function") {
      try {
        document.ariaNotify(message, {
          priority: type === "error" ? "high" : "normal"
        });
        return;
      } catch (e) {}
    }
    var target = type === "error" ? assertiveLive : politeLive;
    if (!target) return;
    target.textContent = "";
    requestAnimationFrame(function () {
      target.textContent = message;
    });
  }

  function finishRemoveToast(record, manualClose) {
    var idx = activeToasts.indexOf(record);
    if (idx !== -1) activeToasts.splice(idx, 1);

    var wasFocused = record.el && record.el.contains(document.activeElement);
    if (record.el && record.el.parentNode) {
      record.el.parentNode.removeChild(record.el);
    }

    if (manualClose && wasFocused) {
      if (activeToasts.length > 0) {
        var nextBtn = activeToasts[0].el.querySelector(".sf-toast-close");
        if (nextBtn) nextBtn.focus();
      } else if (
        record.returnFocus &&
        typeof record.returnFocus.focus === "function" &&
        document.contains(record.returnFocus)
      ) {
        record.returnFocus.focus();
      }
    }

    if (activeToasts.length === 0 && toastRegion) {
      closePopover(toastRegion);
    }
  }

  function dismissToast(record, manualClose) {
    if (!record || record.closing) return;
    record.closing = true;
    clearTimeout(record.timer);
    record.el.setAttribute("data-closing", "");

    var done = false;
    function cleanup() {
      if (done) return;
      done = true;
      finishRemoveToast(record, manualClose);
    }

    if (typeof record.el.getAnimations === "function") {
      var anims = record.el.getAnimations();
      if (anims.length > 0) {
        Promise.race([
          Promise.allSettled(anims.map(function (a) { return a.finished; })),
          new Promise(function (resolve) { setTimeout(resolve, 350); })
        ]).then(cleanup);
        return;
      }
    }
    setTimeout(cleanup, 180);
  }

  function scheduleToastTimer(record) {
    clearTimeout(record.timer);
    if (record.closing || record.hovered || record.focused || record.duration <= 0) return;
    record.timer = setTimeout(function () {
      dismissToast(record, false);
    }, record.duration);
  }

  function showToast(text, options) {
    var opts = options || {};
    var type = opts.type === "success" || opts.type === "error" ? opts.type : "info";
    var key = opts.key || "";
    var vars = opts.vars || null;
    var message = key ? t(key, vars, text || "") : String(text || "");
    if (!message) return null;

    var region = ensureToastRegion();
    if (!region) return null;

    var duration =
      typeof opts.duration === "number"
        ? opts.duration
        : type === "error"
          ? 4500
          : 2800;

    for (var i = 0; i < activeToasts.length; i += 1) {
      var existing = activeToasts[i];
      if (existing.closing) continue;
      if ((key && existing.key === key) || (!key && existing.message === message)) {
        existing.type = type;
        existing.message = message;
        existing.vars = vars;
        existing.duration = duration;
        existing.el.className = "sf-toast is-" + type;
        var iconSpan = existing.el.querySelector(".sf-toast-icon");
        if (iconSpan) iconSpan.innerHTML = ICON_SVGS[type] || ICON_SVGS.info;
        var textSpan = existing.el.querySelector(".sf-toast-text");
        if (textSpan) textSpan.textContent = message;
        openPopoverTop(region, Boolean(document.querySelector("dialog[open]")));
        scheduleToastTimer(existing);
        announceToast(message, type);
        return existing.el;
      }
    }

    while (activeToasts.length >= 4) {
      dismissToast(activeToasts[0], false);
    }

    var el = document.createElement("div");
    el.className = "sf-toast is-" + type;
    el.setAttribute("role", type === "error" ? "alert" : "status");

    var iconWrap = document.createElement("span");
    iconWrap.className = "sf-toast-icon";
    iconWrap.setAttribute("aria-hidden", "true");
    iconWrap.innerHTML = ICON_SVGS[type] || ICON_SVGS.info;
    el.appendChild(iconWrap);

    var msgEl = document.createElement("span");
    msgEl.className = "sf-toast-text";
    msgEl.textContent = message;
    el.appendChild(msgEl);

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "sf-toast-close";
    var closeLabel = t("common.close", null, "关闭");
    closeBtn.setAttribute("aria-label", closeLabel);
    closeBtn.setAttribute("data-i18n-aria-label", "common.close");
    closeBtn.innerHTML = ICON_SVGS.close;
    el.appendChild(closeBtn);

    var record = {
      el: el,
      type: type,
      key: key,
      vars: vars,
      message: message,
      duration: duration,
      hovered: false,
      focused: false,
      closing: false,
      timer: null,
      returnFocus: document.activeElement
    };

    closeBtn.addEventListener("click", function () {
      dismissToast(record, true);
    });
    el.addEventListener("mouseenter", function () {
      record.hovered = true;
      clearTimeout(record.timer);
    });
    el.addEventListener("mouseleave", function () {
      record.hovered = false;
      scheduleToastTimer(record);
    });
    el.addEventListener("focusin", function () {
      record.focused = true;
      clearTimeout(record.timer);
    });
    el.addEventListener("focusout", function (event) {
      if (el.contains(event.relatedTarget)) return;
      record.focused = false;
      scheduleToastTimer(record);
    });

    region.appendChild(el);
    activeToasts.push(record);
    openPopoverTop(region, Boolean(document.querySelector("dialog[open]")));
    scheduleToastTimer(record);
    announceToast(message, type);
    return el;
  }

  function queueToast(text, options) {
    try {
      sessionStorage.setItem(
        TOAST_STORAGE_KEY,
        JSON.stringify({ text: text || "", options: options || {} })
      );
    } catch (e) {}
  }

  function flushQueuedToast() {
    var raw = "";
    try {
      raw = sessionStorage.getItem(TOAST_STORAGE_KEY) || "";
      if (raw) sessionStorage.removeItem(TOAST_STORAGE_KEY);
    } catch (e) {
      raw = "";
    }
    if (!raw) return;
    try {
      var parsed = JSON.parse(raw);
      if (parsed && (parsed.text || (parsed.options && parsed.options.key))) {
        setTimeout(function () {
          showToast(parsed.text, parsed.options);
        }, 40);
      }
    } catch (e) {}
  }

  var tooltipEl = null;
  var activeTrigger = null;
  var showTimer = null;
  var hideTimer = null;
  var triggerHadOwnDescribedBy = false;

  function ensureTooltipEl() {
    if (tooltipEl && document.body && document.body.contains(tooltipEl)) {
      return tooltipEl;
    }
    if (!document.body) return null;
    tooltipEl = document.createElement("div");
    tooltipEl.id = "sf-hover-tooltip";
    tooltipEl.className = "sf-hover-tooltip" + (SUPPORTS_POPOVER ? "" : " sf-popover-fallback");
    tooltipEl.setAttribute("role", "tooltip");
    if (SUPPORTS_POPOVER) {
      tooltipEl.setAttribute("popover", "manual");
    }
    tooltipEl.addEventListener("mouseenter", function () {
      clearTimeout(hideTimer);
    });
    tooltipEl.addEventListener("mouseleave", function () {
      scheduleTooltipHide(110);
    });
    document.body.appendChild(tooltipEl);
    return tooltipEl;
  }

  function resolveTriggerTip(trigger) {
    if (!trigger) return "";
    var key = trigger.getAttribute("data-i18n-hover-tip");
    if (key && window.SiteFlowI18n && window.SiteFlowI18n.t) {
      var vars = null;
      var rawVars = trigger.getAttribute("data-i18n-hover-tip-vars");
      if (rawVars) {
        try {
          vars = JSON.parse(rawVars);
        } catch (e) {
          vars = null;
        }
      }
      var translated = window.SiteFlowI18n.t(key, vars);
      if (translated && translated !== key) {
        trigger.setAttribute("data-hover-tip", translated);
        return translated;
      }
    }
    return (trigger.getAttribute("data-hover-tip") || "").trim();
  }

  function clearTriggerAria() {
    if (activeTrigger && !triggerHadOwnDescribedBy) {
      activeTrigger.removeAttribute("aria-describedby");
    }
    triggerHadOwnDescribedBy = false;
  }

  function hideTooltipImmediate() {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    clearTriggerAria();
    activeTrigger = null;
    if (tooltipEl) {
      closePopover(tooltipEl);
    }
  }

  function scheduleTooltipHide(delay) {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () {
      hideTooltipImmediate();
    }, typeof delay === "number" ? delay : 110);
  }

  function positionTooltip(trigger) {
    var tip = ensureTooltipEl();
    if (!tip || !trigger || !document.contains(trigger)) {
      hideTooltipImmediate();
      return;
    }
    var text = resolveTriggerTip(trigger);
    if (!text) {
      hideTooltipImmediate();
      return;
    }

    tip.textContent = text;
    tip.style.left = "-9999px";
    tip.style.top = "-9999px";
    openPopoverTop(tip, Boolean(document.querySelector("dialog[open]")));

    var triggerRect = trigger.getBoundingClientRect();
    var tipRect = tip.getBoundingClientRect();
    if (triggerRect.width === 0 && triggerRect.height === 0) {
      hideTooltipImmediate();
      return;
    }

    var gap = 8;
    var pad = 10;
    var vw = window.innerWidth;
    var vh = window.innerHeight;

    var placement = "top";
    var top = triggerRect.top - tipRect.height - gap;
    if (top < pad) {
      var below = triggerRect.bottom + gap;
      if (below + tipRect.height <= vh - pad || vh - triggerRect.bottom >= triggerRect.top) {
        placement = "bottom";
        top = below;
      }
    }
    top = Math.max(pad, Math.min(top, Math.max(pad, vh - tipRect.height - pad)));

    var triggerCenterX = triggerRect.left + triggerRect.width / 2;
    var left = triggerCenterX - tipRect.width / 2;
    left = Math.max(pad, Math.min(left, Math.max(pad, vw - tipRect.width - pad)));

    var arrowX = Math.max(14, Math.min(tipRect.width - 14, triggerCenterX - left));

    tip.setAttribute("data-placement", placement);
    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
    tip.style.setProperty("--sf-tip-arrow-x", Math.round(arrowX) + "px");
  }

  function showTooltipFor(trigger, immediate) {
    if (!trigger) return;
    clearTimeout(hideTimer);
    clearTimeout(showTimer);
    var alreadyVisible = tooltipEl && isPopoverOpen(tooltipEl);
    var delay = immediate || alreadyVisible ? 0 : 70;

    function activate() {
      if (!document.contains(trigger)) return;
      if (activeTrigger !== trigger) {
        clearTriggerAria();
        activeTrigger = trigger;
        triggerHadOwnDescribedBy = trigger.hasAttribute("aria-describedby");
        if (!triggerHadOwnDescribedBy) {
          trigger.setAttribute("aria-describedby", "sf-hover-tooltip");
        }
      }
      positionTooltip(trigger);
    }

    if (delay === 0) {
      activate();
    } else {
      showTimer = setTimeout(activate, delay);
    }
  }

  document.addEventListener("mouseover", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    if (tooltipEl && tooltipEl.contains(target)) {
      clearTimeout(hideTimer);
      return;
    }
    var trigger = target.closest("[data-hover-tip]");
    if (!trigger) return;
    if (trigger === activeTrigger && tooltipEl && isPopoverOpen(tooltipEl)) {
      clearTimeout(hideTimer);
      return;
    }
    showTooltipFor(trigger, false);
  });

  document.addEventListener("mouseout", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var trigger = target.closest("[data-hover-tip]");
    if (!trigger) return;
    var related = event.relatedTarget;
    if (related && (trigger.contains(related) || (tooltipEl && tooltipEl.contains(related)))) {
      return;
    }
    if (trigger === activeTrigger) {
      scheduleTooltipHide(120);
    } else {
      clearTimeout(showTimer);
    }
  });

  document.addEventListener("focusin", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var trigger = target.closest("[data-hover-tip]");
    if (!trigger) return;
    showTooltipFor(trigger, true);
  });

  document.addEventListener("focusout", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var trigger = target.closest("[data-hover-tip]");
    if (!trigger) return;
    if (trigger === activeTrigger) {
      scheduleTooltipHide(60);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && tooltipEl && isPopoverOpen(tooltipEl)) {
      hideTooltipImmediate();
    }
  });

  window.addEventListener(
    "scroll",
    function () {
      if (tooltipEl && isPopoverOpen(tooltipEl)) {
        hideTooltipImmediate();
      }
    },
    true
  );
  window.addEventListener("resize", function () {
    if (activeTrigger && tooltipEl && isPopoverOpen(tooltipEl)) {
      positionTooltip(activeTrigger);
    }
  });

  window.addEventListener("siteflow:langchange", function () {
    if (toastRegion) {
      toastRegion.setAttribute("aria-label", t("ui.toast_region", null, "通知"));
    }
    activeToasts.forEach(function (record) {
      if (record.key) {
        record.message = t(record.key, record.vars, record.message);
        var textSpan = record.el.querySelector(".sf-toast-text");
        if (textSpan) textSpan.textContent = record.message;
      }
      var closeBtn = record.el.querySelector(".sf-toast-close");
      if (closeBtn) closeBtn.setAttribute("aria-label", t("common.close", null, "关闭"));
    });
    if (activeTrigger && tooltipEl && isPopoverOpen(tooltipEl)) {
      positionTooltip(activeTrigger);
    }
  });

  window.SiteFlowToast = {
    show: showToast,
    queue: queueToast
  };

  window.SiteFlowTooltip = {
    hide: hideTooltipImmediate,
    show: showTooltipFor,
    refresh: function () {
      if (activeTrigger && tooltipEl && isPopoverOpen(tooltipEl)) {
        positionTooltip(activeTrigger);
      }
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", flushQueuedToast);
  } else {
    flushQueuedToast();
  }
})();
