(function () {
  "use strict";

  var cfgEl = document.getElementById("bottle-config");
  if (!cfgEl) return;
  var cfg = JSON.parse(cfgEl.textContent || "{}");

  var throwForm = document.getElementById("bottle-throw-form");
  var msgInput = document.getElementById("bottle-message");
  var nickInput = document.getElementById("bottle-nickname");
  var hpInput = document.getElementById("bottle-website");
  var charCount = document.getElementById("bottle-char-count");
  var msgError = document.getElementById("bottle-message-error");
  var throwBtn = document.getElementById("bottle-throw-btn");
  var throwStatus = document.getElementById("throw-status");

  var pickBtn = document.getElementById("bottle-pick-btn");
  var pickStatus = document.getElementById("pick-status");
  var oceanEl = document.getElementById("bottle-ocean");
  var noteCard = document.getElementById("picked-note");
  var noteBody = document.getElementById("picked-note-body");
  var noteAuthor = document.getElementById("picked-note-author");
  var noteDate = document.getElementById("picked-note-date");

  var creditsEl = document.getElementById("bottle-credits");
  var seaCountEl = document.getElementById("bottle-sea-count");
  var lastPicked = null;

  function t(key, vars, fallback) {
    if (window.SiteFlowI18n && window.SiteFlowI18n.t) {
      return window.SiteFlowI18n.t(key, vars);
    }
    return fallback || key;
  }

  function translateMessage(text) {
    if (!text) return "";
    if (window.SiteFlowI18n && window.SiteFlowI18n.translateText) {
      return window.SiteFlowI18n.translateText(text);
    }
    return text;
  }

  function linkError(el, shown) {
    var errorId = el.getAttribute("data-error");
    if (!errorId) return;
    var ids = (el.getAttribute("aria-describedby") || "")
      .split(/\s+/)
      .filter(function (id) { return id && id !== errorId; });
    if (shown) ids.push(errorId);
    if (ids.length) el.setAttribute("aria-describedby", ids.join(" "));
    else el.removeAttribute("aria-describedby");
  }

  function showFieldError(text) {
    if (!msgError || !msgInput) return;
    msgError.textContent = text;
    msgError.hidden = !text;
    var isBad = Boolean(text);
    msgInput.setAttribute("aria-invalid", isBad ? "true" : "false");
    msgInput.classList.toggle("user-invalid-fallback", isBad);
    linkError(msgInput, isBad);
  }

  function setFeedback(el, kind, message) {
    if (!el) return;
    el.classList.remove("is-success", "is-error");
    if (!message) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = translateMessage(message);
    if (kind === "success") el.classList.add("is-success");
    if (kind === "error") el.classList.add("is-error");
  }

  function updateCounter() {
    if (!msgInput || !charCount) return;
    var len = msgInput.value.length;
    var maxLen = cfg.max_length || 280;
    charCount.textContent = len + " / " + maxLen;
    charCount.classList.toggle("is-warn", len >= Math.floor(maxLen * 0.85) && len < maxLen);
    charCount.classList.toggle("is-limit", len >= maxLen);
  }

  function updateCredits(nextCredits) {
    if (typeof nextCredits !== "number") return;
    cfg.credits = nextCredits;
    if (creditsEl) {
      creditsEl.textContent = String(nextCredits);
    }
  }

  function renderPickedNote(bottle) {
    if (!noteCard || !noteBody || !noteAuthor || !noteDate) return;
    lastPicked = bottle;
    if (!bottle) {
      noteCard.hidden = true;
      return;
    }
    noteBody.textContent = bottle.message || "";
    noteAuthor.textContent = bottle.nickname || t("bottle.anonymous_author", null, "匿名旅人");
    noteDate.textContent = bottle.date || "";
    noteCard.hidden = false;
    noteCard.classList.remove("is-revealed");
    void noteCard.offsetWidth;
    noteCard.classList.add("is-revealed");
  }

  if (msgInput) {
    updateCounter();
    msgInput.addEventListener("input", function () {
      updateCounter();
      if (msgInput.value.trim().length > 0 && msgInput.value.length <= (cfg.max_length || 280)) {
        showFieldError("");
      }
    });
    msgInput.addEventListener("blur", function () {
      if (msgInput.value.length > 0 && !msgInput.value.trim()) {
        showFieldError(t("bottle.err_empty", null, "写点什么再把瓶子投进海里吧"));
      }
    });
  }

  if (throwForm) {
    throwForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!msgInput || !throwBtn) return;
      var rawMessage = msgInput.value.trim();
      var maxLen = cfg.max_length || 280;
      if (!rawMessage) {
        showFieldError(t("bottle.err_empty", null, "写点什么再把瓶子投进海里吧"));
        msgInput.focus();
        return;
      }
      if (rawMessage.length > maxLen) {
        showFieldError(t("bottle.err_too_long", { max: maxLen }, "内容不能超过 " + maxLen + " 字"));
        msgInput.focus();
        return;
      }
      showFieldError("");
      setFeedback(throwStatus, "", "");
      throwBtn.disabled = true;

      fetch("/api/projects/" + encodeURIComponent(cfg.slug) + "/bottle/throw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: rawMessage,
          nickname: nickInput ? nickInput.value.trim() : "",
          website: hpInput ? hpInput.value : ""
        })
      })
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (data) {
            if (!response.ok || data.ok === false) {
              throw new Error(data.error || t("js.req_failed", null, "请求失败"));
            }
            return data;
          });
        })
        .then(function (data) {
          throwForm.reset();
          showFieldError("");
          updateCounter();
          updateCredits(data.credits);
          if (typeof data.approved_count === "number" && seaCountEl) {
            cfg.approved_count = data.approved_count;
            seaCountEl.textContent = String(data.approved_count);
          } else if (data.status === "approved" && seaCountEl) {
            cfg.approved_count = (cfg.approved_count || 0) + 1;
            seaCountEl.textContent = String(cfg.approved_count);
          }
          var defaultMsg = cfg.require_approval
            ? t("bottle.thrown_pending", null, "已入海，等待站长审核后漂向远方")
            : t("bottle.thrown_approved", null, "漂流瓶已顺利入海，漂向远方");
          setFeedback(throwStatus, "success", data.message || defaultMsg);
        })
        .catch(function (error) {
          setFeedback(throwStatus, "error", error.message || t("js.req_failed", null, "请求失败"));
        })
        .finally(function () {
          throwBtn.disabled = false;
        });
    });
  }

  if (pickBtn) {
    pickBtn.addEventListener("click", function () {
      pickBtn.disabled = true;
      setFeedback(pickStatus, "", "");
      if (oceanEl) {
        oceanEl.classList.remove("is-picking");
        void oceanEl.offsetWidth;
        oceanEl.classList.add("is-picking");
      }
      var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      var minDelay = reducedMotion ? 0 : 380;
      var started = Date.now();

      fetch("/api/projects/" + encodeURIComponent(cfg.slug) + "/bottle/pick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      })
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (data) {
            if (!response.ok || data.ok === false) {
              throw new Error(data.error || t("js.req_failed", null, "请求失败"));
            }
            return data;
          });
        })
        .then(function (data) {
          var elapsed = Date.now() - started;
          var wait = Math.max(0, minDelay - elapsed);
          return new Promise(function (resolve) {
            setTimeout(function () { resolve(data); }, wait);
          });
        })
        .then(function (data) {
          updateCredits(data.credits);
          if (typeof data.approved_count === "number" && seaCountEl) {
            cfg.approved_count = data.approved_count;
            seaCountEl.textContent = String(data.approved_count);
          }
          if (data.empty || !data.bottle) {
            setFeedback(
              pickStatus,
              "",
              data.message || t("bottle.pick_empty", null, "此刻海面风平浪静，暂时没有来自他人的漂流瓶，稍后再来试试吧")
            );
            return;
          }
          renderPickedNote(data.bottle);
        })
        .catch(function (error) {
          setFeedback(pickStatus, "error", error.message || t("js.req_failed", null, "请求失败"));
        })
        .finally(function () {
          pickBtn.disabled = false;
          if (oceanEl) {
            setTimeout(function () { oceanEl.classList.remove("is-picking"); }, 220);
          }
        });
    });
  }

  window.addEventListener("siteflow:langchange", function () {
    if (lastPicked) {
      noteAuthor.textContent = lastPicked.nickname || t("bottle.anonymous_author", null, "匿名旅人");
    }
  });
})();
