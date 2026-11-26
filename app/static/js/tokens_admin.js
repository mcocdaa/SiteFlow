(function () {
  "use strict";

  var dialog = document.getElementById("api-tokens-dialog");
  var openBtn = document.getElementById("api-tokens-open-btn");
  if (!dialog || !openBtn) return;

  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute("content") || "" : "";

  var formEl = dialog.querySelector("[data-tokens-form]");
  var nameInput = formEl ? formEl.querySelector('input[name="name"]') : null;
  var expirySelect = formEl ? formEl.querySelector('select[name="expiry_days"]') : null;
  var submitBtn = dialog.querySelector("[data-tokens-submit]");
  var submitLabel = dialog.querySelector("[data-tokens-submit-label]");
  var presetBtns = Array.prototype.slice.call(dialog.querySelectorAll("[data-token-preset]"));
  var scopeInputs = Array.prototype.slice.call(dialog.querySelectorAll('input[name="scopes"]'));

  var projectsStatusEl = dialog.querySelector("[data-tokens-projects-status]");
  var clearProjectsBtn = dialog.querySelector("[data-tokens-clear-projects]");
  var projectSearchEl = dialog.querySelector("[data-tokens-project-search]");
  var projectsListEl = dialog.querySelector("[data-tokens-projects-list]");
  var projectsEmptyEl = dialog.querySelector("[data-tokens-projects-empty]");
  var projectsNoMatchEl = dialog.querySelector("[data-tokens-projects-nomatch]");

  var secretBannerEl = dialog.querySelector("[data-tokens-secret-banner]");
  var secretValueEl = dialog.querySelector("[data-tokens-secret-value]");
  var secretCopyBtn = dialog.querySelector("[data-tokens-copy-secret]");
  var secretCopyIconEl = dialog.querySelector("[data-tokens-copy-icon]");
  var secretCopyLabelEl = dialog.querySelector("[data-tokens-copy-label]");
  var secretDismissBtn = dialog.querySelector("[data-tokens-secret-dismiss]");

  var listEl = dialog.querySelector("[data-tokens-list]");
  var countEl = dialog.querySelector("[data-tokens-count]");
  var loadingEl = dialog.querySelector("[data-tokens-loading]");
  var emptyEl = dialog.querySelector("[data-tokens-empty]");
  var refreshBtn = dialog.querySelector("[data-tokens-refresh]");

  var ALL_SCOPES = [
    "read",
    "posts:write",
    "content:write",
    "projects:write",
    "deploy:write",
    "submissions:write",
    "extensions:write",
    "admin"
  ];

  var PRESETS = {
    readonly: ["read"],
    blog: ["read", "posts:write"],
    admin: ALL_SCOPES.slice()
  };

  var TYPE_LABELS = {
    space: { key: "tokens.type_space", fallback: "空间" },
    blog: { key: "tokens.type_blog", fallback: "博客" },
    resume: { key: "tokens.type_resume", fallback: "简历" },
    bottle: { key: "tokens.type_bottle", fallback: "漂流瓶" },
    link: { key: "tokens.type_link", fallback: "外链" },
    html: { key: "tokens.type_static", fallback: "静态" },
    zip: { key: "tokens.type_static", fallback: "静态" },
    static: { key: "tokens.type_static", fallback: "静态" }
  };

  var issuedTokens = [];
  var projects = [];
  var selectedSlugs = {};
  var projectQuery = "";
  var activeSecret = "";
  var copyResetTimer = null;
  var loading = false;
  var submitting = false;

  function getLang() {
    return window.SiteFlowI18n && window.SiteFlowI18n.getLang
      ? window.SiteFlowI18n.getLang()
      : "zh";
  }

  function t(key, vars, fallback) {
    if (key && window.SiteFlowI18n && window.SiteFlowI18n.t) {
      var val = window.SiteFlowI18n.t(key, vars);
      if (val !== key || !fallback) return val;
    }
    return fallback !== undefined ? fallback : key || "";
  }

  function trError(text) {
    if (!text) return "";
    return window.SiteFlowI18n && window.SiteFlowI18n.translateText
      ? window.SiteFlowI18n.translateText(text)
      : text;
  }

  function showToast(text, type, key, vars) {
    if (window.SiteFlowToast && window.SiteFlowToast.show) {
      window.SiteFlowToast.show(text, {
        type: type || "info",
        key: key || "",
        vars: vars || null
      });
    }
  }

  function hideTooltip() {
    if (window.SiteFlowTooltip && window.SiteFlowTooltip.hide) {
      window.SiteFlowTooltip.hide();
    }
  }

  function cloneIcon(name) {
    var tpl = dialog.querySelector('[data-token-icon-tpl="' + name + '"]');
    if (tpl && tpl.content) {
      return tpl.content.cloneNode(true);
    }
    return document.createDocumentFragment();
  }

  function setHoverTip(el, text, key) {
    if (!el) return;
    el.setAttribute("data-hover-tip", text || "");
    if (key) {
      el.setAttribute("data-i18n-hover-tip", key);
    } else {
      el.removeAttribute("data-i18n-hover-tip");
    }
  }

  async function apiJson(method, url, payload) {
    var headers = { "X-CSRF-Token": csrf };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    var response;
    try {
      response = await fetch(url, {
        method: method,
        headers: headers,
        body: payload === undefined ? undefined : JSON.stringify(payload)
      });
    } catch (error) {
      throw new Error(t("js.network_error", null, "网络错误"));
    }
    var data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error(t("js.req_failed", null, "请求失败") + " (HTTP " + response.status + ")");
    }
    if (!response.ok || data.ok === false) {
      var detail = data.error || (typeof data.detail === "string" ? data.detail : "");
      throw new Error(detail ? trError(detail) : t("js.req_failed", null, "请求失败"));
    }
    return data;
  }

  function getSelectedScopes() {
    var out = [];
    scopeInputs.forEach(function (input) {
      if (input.checked) out.push(input.value);
    });
    return out;
  }

  function getSelectedSlugs() {
    return Object.keys(selectedSlugs).filter(function (slug) {
      return Boolean(selectedSlugs[slug]);
    });
  }

  function setSelectedScopes(list) {
    var lookup = {};
    list.forEach(function (s) {
      lookup[s] = true;
    });
    scopeInputs.forEach(function (input) {
      input.checked = Boolean(lookup[input.value]);
    });
    syncPresetChips();
  }

  function sameSet(a, b) {
    if (a.length !== b.length) return false;
    var map = {};
    a.forEach(function (item) {
      map[item] = true;
    });
    for (var i = 0; i < b.length; i += 1) {
      if (!map[b[i]]) return false;
    }
    return true;
  }

  function syncPresetChips() {
    var currentScopes = getSelectedScopes();
    var slugCount = getSelectedSlugs().length;
    presetBtns.forEach(function (btn) {
      var presetKey = btn.getAttribute("data-token-preset") || "";
      var expected = PRESETS[presetKey] || [];
      var active = sameSet(currentScopes, expected);
      if (presetKey === "admin" && slugCount > 0) {
        active = false;
      }
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function buildProjectPathMap() {
    var byId = {};
    projects.forEach(function (p) {
      byId[p.id] = p;
    });
    var paths = {};
    projects.forEach(function (p) {
      var parts = [p.title || p.slug];
      var cur = p;
      var guard = 0;
      while (cur && cur.parent_id && byId[cur.parent_id] && guard < 5) {
        cur = byId[cur.parent_id];
        parts.unshift(cur.title || cur.slug);
        guard += 1;
      }
      paths[p.slug] = parts.join(" / ");
    });
    return paths;
  }

  function updateProjectsStatus() {
    var slugs = getSelectedSlugs();
    if (projectsStatusEl) {
      if (slugs.length === 0) {
        projectsStatusEl.textContent = t("tokens.projects_all_site", null, "全站生效");
        projectsStatusEl.classList.remove("is-scoped");
      } else {
        projectsStatusEl.textContent = t(
          "tokens.projects_selected_count",
          { n: slugs.length },
          "已选 " + slugs.length + " 项"
        );
        projectsStatusEl.classList.add("is-scoped");
      }
    }
    if (clearProjectsBtn) {
      clearProjectsBtn.hidden = slugs.length === 0;
    }
    syncPresetChips();
  }

  function renderProjectPicker() {
    if (!projectsListEl) return;
    projectsListEl.textContent = "";
    if (projects.length === 0) {
      projectsListEl.hidden = true;
      if (projectsEmptyEl) projectsEmptyEl.hidden = false;
      if (projectsNoMatchEl) projectsNoMatchEl.hidden = true;
      updateProjectsStatus();
      return;
    }
    projectsListEl.hidden = false;
    if (projectsEmptyEl) projectsEmptyEl.hidden = true;

    var query = (projectQuery || "").trim().toLowerCase();
    var pathMap = buildProjectPathMap();
    var visibleCount = 0;

    projects.forEach(function (proj) {
      var fullPath = pathMap[proj.slug] || proj.title || proj.slug;
      var hay = (fullPath + " " + proj.slug + " " + (proj.type || "")).toLowerCase();
      if (query && hay.indexOf(query) === -1) return;
      visibleCount += 1;

      var isSelected = Boolean(selectedSlugs[proj.slug]);
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "tokens-project-chip" + (isSelected ? " is-selected" : "");
      chip.setAttribute("data-token-project-slug", proj.slug);
      chip.setAttribute("aria-pressed", isSelected ? "true" : "false");

      var typeMeta = TYPE_LABELS[proj.type] || TYPE_LABELS.static;
      var typeBadge = document.createElement("span");
      typeBadge.className = "tokens-project-type";
      typeBadge.textContent = t(typeMeta.key, null, typeMeta.fallback);
      chip.appendChild(typeBadge);

      var nameSpan = document.createElement("span");
      nameSpan.className = "tokens-project-name";
      nameSpan.textContent = fullPath;
      chip.appendChild(nameSpan);

      var slugCode = document.createElement("code");
      slugCode.className = "tokens-project-slug";
      slugCode.textContent = proj.slug;
      chip.appendChild(slugCode);

      projectsListEl.appendChild(chip);
    });

    if (projectsNoMatchEl) {
      projectsNoMatchEl.hidden = visibleCount > 0;
    }
    updateProjectsStatus();
  }

  function formatDateTime(iso) {
    if (!iso) return "";
    var date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    try {
      var locale = getLang() === "en" ? "en-US" : "zh-CN";
      return new Intl.DateTimeFormat(locale, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      }).format(date);
    } catch (e) {
      return iso.slice(0, 16).replace("T", " ");
    }
  }

  function isExpired(iso) {
    if (!iso) return false;
    var time = Date.parse(iso);
    if (isNaN(time)) return false;
    return time <= Date.now();
  }

  function renderTokensList() {
    if (!listEl) return;
    listEl.textContent = "";
    if (countEl) {
      countEl.textContent = String(issuedTokens.length);
    }
    if (loadingEl) loadingEl.hidden = !loading;
    if (emptyEl) emptyEl.hidden = loading || issuedTokens.length > 0;
    if (loading || issuedTokens.length === 0) return;

    var pathMap = buildProjectPathMap();

    issuedTokens.forEach(function (item) {
      var expired = isExpired(item.expires_at);
      var card = document.createElement("article");
      card.className = "token-item" + (expired ? " is-expired" : "");
      card.setAttribute("data-token-id", String(item.id));

      var head = document.createElement("div");
      head.className = "token-item-head";

      var ident = document.createElement("div");
      ident.className = "token-item-ident";

      var nameEl = document.createElement("strong");
      nameEl.className = "token-item-name";
      nameEl.textContent = item.name;
      ident.appendChild(nameEl);

      var prefixEl = document.createElement("code");
      prefixEl.className = "token-prefix-pill";
      prefixEl.textContent = (item.prefix || "sft_") + "...";
      ident.appendChild(prefixEl);

      if (expired) {
        var expBadge = document.createElement("span");
        expBadge.className = "token-status-badge is-expired";
        expBadge.textContent = t("tokens.badge_expired", null, "已过期");
        ident.appendChild(expBadge);
      }

      head.appendChild(ident);

      var revokeBtn = document.createElement("button");
      revokeBtn.type = "button";
      revokeBtn.className = "btn danger icon-btn btn-sm";
      revokeBtn.setAttribute("data-token-revoke", String(item.id));
      revokeBtn.setAttribute("data-token-name", item.name);
      var revokeTip = t("tokens.revoke_tip", null, "吊销令牌");
      setHoverTip(revokeBtn, revokeTip, "tokens.revoke_tip");
      revokeBtn.setAttribute("aria-label", revokeTip);
      revokeBtn.appendChild(cloneIcon("trash"));
      head.appendChild(revokeBtn);

      card.appendChild(head);

      var tagsRow = document.createElement("div");
      tagsRow.className = "token-item-tags";

      (item.scopes || []).forEach(function (scope) {
        var pill = document.createElement("span");
        pill.className = "token-scope-pill" + (scope === "admin" ? " is-admin" : "");
        pill.textContent = scope;
        tagsRow.appendChild(pill);
      });

      var slugs = item.allowed_slugs || [];
      if (slugs.length === 0) {
        var sitePill = document.createElement("span");
        sitePill.className = "token-target-pill is-site-wide";
        sitePill.textContent = t("tokens.scope_site_wide", null, "全站");
        tagsRow.appendChild(sitePill);
      } else {
        slugs.forEach(function (slug) {
          var slugPill = document.createElement("span");
          slugPill.className = "token-target-pill";
          slugPill.textContent = slug;
          if (pathMap[slug]) {
            setHoverTip(slugPill, pathMap[slug]);
          }
          tagsRow.appendChild(slugPill);
        });
      }
      card.appendChild(tagsRow);

      var metaRow = document.createElement("div");
      metaRow.className = "token-item-meta";

      var createdSpan = document.createElement("span");
      createdSpan.textContent =
        t("tokens.meta_created", null, "创建") + ": " + formatDateTime(item.created_at);
      metaRow.appendChild(createdSpan);

      var lastUsedSpan = document.createElement("span");
      lastUsedSpan.textContent =
        t("tokens.meta_last_used", null, "最近使用") +
        ": " +
        (item.last_used_at
          ? formatDateTime(item.last_used_at)
          : t("tokens.meta_never_used", null, "从未使用"));
      metaRow.appendChild(lastUsedSpan);

      var expiresSpan = document.createElement("span");
      expiresSpan.textContent =
        t("tokens.meta_expires", null, "有效期") +
        ": " +
        (item.expires_at
          ? formatDateTime(item.expires_at)
          : t("tokens.expiry_never", null, "永不过期"));
      metaRow.appendChild(expiresSpan);

      card.appendChild(metaRow);
      listEl.appendChild(card);
    });
  }

  function showSecretBanner(plaintext) {
    activeSecret = plaintext || "";
    if (!secretBannerEl || !secretValueEl) return;
    secretValueEl.textContent = activeSecret;
    secretBannerEl.hidden = !activeSecret;
    resetCopyButtonState();
    if (activeSecret) {
      secretBannerEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function hideSecretBanner() {
    activeSecret = "";
    if (secretValueEl) secretValueEl.textContent = "";
    if (secretBannerEl) secretBannerEl.hidden = true;
    resetCopyButtonState();
  }

  function resetCopyButtonState() {
    clearTimeout(copyResetTimer);
    if (secretCopyIconEl) {
      secretCopyIconEl.textContent = "";
      secretCopyIconEl.appendChild(cloneIcon("copy"));
    }
    if (secretCopyLabelEl) {
      secretCopyLabelEl.textContent = t("tokens.secret_copy", null, "复制令牌");
    }
  }

  function fallbackCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }

  async function copyActiveSecret() {
    if (!activeSecret) return;
    var copied = false;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(activeSecret);
        copied = true;
      } catch (e) {
        copied = fallbackCopy(activeSecret);
      }
    } else {
      copied = fallbackCopy(activeSecret);
    }
    if (copied) {
      clearTimeout(copyResetTimer);
      if (secretCopyIconEl) {
        secretCopyIconEl.textContent = "";
        secretCopyIconEl.appendChild(cloneIcon("check"));
      }
      if (secretCopyLabelEl) {
        secretCopyLabelEl.textContent = t("tokens.secret_copied", null, "已复制");
      }
      showToast(t("tokens.toast_copied", null, "已复制 API 令牌"), "success", "tokens.toast_copied");
      copyResetTimer = setTimeout(resetCopyButtonState, 1800);
    } else {
      showToast(
        t("tokens.toast_copy_failed", null, "复制失败，请手动选中复制"),
        "error",
        "tokens.toast_copy_failed"
      );
    }
  }

  async function loadTokensAndProjects() {
    loading = true;
    renderTokensList();
    try {
      var data = await apiJson("GET", "/api/admin/tokens");
      issuedTokens = Array.isArray(data.tokens) ? data.tokens : [];
      if (Array.isArray(data.projects)) {
        projects = data.projects;
      } else {
        var projRes = await apiJson("GET", "/api/admin/projects");
        projects = Array.isArray(projRes.projects) ? projRes.projects : [];
      }
      if (Array.isArray(data.valid_scopes) && data.valid_scopes.length > 0) {
        ALL_SCOPES = data.valid_scopes.slice();
        PRESETS.admin = ALL_SCOPES.slice();
      }
    } catch (error) {
      showToast(error.message || t("js.req_failed", null, "请求失败"), "error");
    } finally {
      loading = false;
      renderProjectPicker();
      renderTokensList();
    }
  }

  function computeExpiresAt(daysValue) {
    var days = parseInt(daysValue || "", 10);
    if (!days || days <= 0) return "";
    return new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
  }

  async function handleCreateSubmit(event) {
    event.preventDefault();
    if (submitting) return;
    var name = nameInput ? nameInput.value.trim() : "";
    if (!name) {
      showToast(t("tokens.err_name_required", null, "请输入令牌名称"), "error", "tokens.err_name_required");
      if (nameInput) nameInput.focus();
      return;
    }
    var scopes = getSelectedScopes();
    if (scopes.length === 0) {
      showToast(
        t("tokens.err_scope_required", null, "请至少选择一个权限范围"),
        "error",
        "tokens.err_scope_required"
      );
      return;
    }
    var allowedSlugs = getSelectedSlugs();
    var expiresAt = computeExpiresAt(expirySelect ? expirySelect.value : "");

    submitting = true;
    if (submitBtn) submitBtn.disabled = true;
    if (submitLabel) submitLabel.textContent = t("tokens.creating_btn", null, "生成中…");
    try {
      var data = await apiJson("POST", "/api/admin/tokens", {
        name: name,
        scopes: scopes,
        allowed_slugs: allowedSlugs,
        expires_at: expiresAt
      });
      if (data.token) {
        issuedTokens.unshift(data.token);
      }
      showSecretBanner(data.plaintext || "");
      if (nameInput) nameInput.value = "";
      if (expirySelect) expirySelect.value = "";
      renderTokensList();
      showToast(
        t("tokens.toast_created", null, "API 令牌已生成，请及时复制保存"),
        "success",
        "tokens.toast_created"
      );
    } catch (error) {
      showToast(error.message || t("js.req_failed", null, "请求失败"), "error");
    } finally {
      submitting = false;
      if (submitBtn) submitBtn.disabled = false;
      if (submitLabel) submitLabel.textContent = t("tokens.create_btn", null, "生成令牌");
    }
  }

  async function handleRevoke(tokenId, tokenName, button) {
    var msg = t(
      "tokens.confirm_revoke",
      { name: tokenName || "" },
      "确定吊销令牌「" + (tokenName || "") + "」？吊销后该令牌将立即失效且不可恢复。"
    );
    if (!window.confirm(msg)) return;
    hideTooltip();
    if (button) button.disabled = true;
    try {
      await apiJson("DELETE", "/api/admin/tokens/" + encodeURIComponent(String(tokenId)));
      issuedTokens = issuedTokens.filter(function (item) {
        return String(item.id) !== String(tokenId);
      });
      renderTokensList();
      showToast(t("tokens.toast_revoked", null, "API 令牌已吊销"), "success", "tokens.toast_revoked");
    } catch (error) {
      if (button) button.disabled = false;
      showToast(error.message || t("js.req_failed", null, "请求失败"), "error");
    }
  }

  openBtn.addEventListener("click", function () {
    hideTooltip();
    if (!dialog.open) {
      dialog.showModal();
    }
    loadTokensAndProjects();
  });

  dialog.querySelectorAll("[data-tokens-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      dialog.close();
    });
  });

  dialog.addEventListener("close", function () {
    hideTooltip();
    hideSecretBanner();
  });

  if (!("closedBy" in HTMLDialogElement.prototype)) {
    var isOutsideDialog = function (e) {
      var r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    var pressedOutside = false;
    dialog.addEventListener("pointerdown", function (e) {
      pressedOutside = isOutsideDialog(e);
    });
    dialog.addEventListener("pointerup", function (e) {
      if (pressedOutside && isOutsideDialog(e)) {
        dialog.close();
      }
      pressedOutside = false;
    });
  }

  presetBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var presetKey = btn.getAttribute("data-token-preset") || "";
      var scopes = PRESETS[presetKey];
      if (!scopes) return;
      if (presetKey === "admin") {
        selectedSlugs = {};
        renderProjectPicker();
      }
      setSelectedScopes(scopes);
    });
  });

  scopeInputs.forEach(function (input) {
    input.addEventListener("change", syncPresetChips);
  });

  if (clearProjectsBtn) {
    clearProjectsBtn.addEventListener("click", function () {
      selectedSlugs = {};
      renderProjectPicker();
    });
  }

  if (projectSearchEl) {
    projectSearchEl.addEventListener("input", function () {
      projectQuery = projectSearchEl.value || "";
      renderProjectPicker();
    });
  }

  if (projectsListEl) {
    projectsListEl.addEventListener("click", function (event) {
      var chip = event.target.closest("[data-token-project-slug]");
      if (!chip) return;
      var slug = chip.getAttribute("data-token-project-slug") || "";
      if (!slug) return;
      if (selectedSlugs[slug]) {
        delete selectedSlugs[slug];
      } else {
        selectedSlugs[slug] = true;
      }
      renderProjectPicker();
    });
  }

  if (formEl) {
    formEl.addEventListener("submit", handleCreateSubmit);
  }

  if (secretCopyBtn) {
    secretCopyBtn.addEventListener("click", copyActiveSecret);
  }

  if (secretDismissBtn) {
    secretDismissBtn.addEventListener("click", hideSecretBanner);
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      loadTokensAndProjects();
    });
  }

  if (listEl) {
    listEl.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-token-revoke]");
      if (!btn) return;
      var tokenId = btn.getAttribute("data-token-revoke") || "";
      var tokenName = btn.getAttribute("data-token-name") || "";
      if (tokenId) {
        handleRevoke(tokenId, tokenName, btn);
      }
    });
  }

  window.addEventListener("siteflow:langchange", function () {
    renderProjectPicker();
    renderTokensList();
    if (submitLabel && !submitting) {
      submitLabel.textContent = t("tokens.create_btn", null, "生成令牌");
    }
    if (secretCopyLabelEl) {
      secretCopyLabelEl.textContent = t("tokens.secret_copy", null, "复制令牌");
    }
  });

  syncPresetChips();
})();
