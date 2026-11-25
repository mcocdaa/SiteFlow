(function () {
  "use strict";

  var panel = document.querySelector("[data-ext-panel]");
  if (!panel) return;

  var scope = panel.dataset.extScope === "site" ? "site" : "project";
  var targetType = panel.dataset.extTarget || "";
  var projectId = panel.dataset.projectId || "";
  var base = scope === "site"
    ? "/api/admin/site"
    : "/api/admin/projects/" + encodeURIComponent(projectId);
  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var csrf = csrfMeta ? csrfMeta.content : "";

  var siteDialogEl = scope === "site" ? document.getElementById("site-ext-dialog") : null;
  var siteOpenBtn = scope === "site" ? document.getElementById("site-ext-open-btn") : null;
  var siteActiveCountEl = scope === "site" ? document.querySelector("[data-site-ext-active-count]") : null;

  var gridEl = panel.querySelector("[data-ext-grid]");
  var searchEl = panel.querySelector("[data-ext-search]");
  var packFiltersEl = panel.querySelector("[data-ext-pack-filters]");
  var filterEmptyEl = panel.querySelector("[data-ext-filter-empty]");
  var packsToggleEl = panel.querySelector("[data-ext-packs-toggle]");
  var packsPanelEl = panel.querySelector("[data-ext-packs-panel]");
  var packUrlFormEl = panel.querySelector("[data-ext-pack-url-form]");
  var packUploadBtn = panel.querySelector("[data-ext-pack-upload]");
  var packsListEl = panel.querySelector("[data-ext-packs-list]");

  var drawerBackdropEl = panel.querySelector("[data-ext-drawer-backdrop]");
  var drawerEl = panel.querySelector("[data-ext-drawer]");
  var drawerIconEl = panel.querySelector("[data-ext-drawer-icon]");
  var drawerTitleEl = panel.querySelector("[data-ext-drawer-title]");
  var drawerVersionEl = panel.querySelector("[data-ext-drawer-version]");
  var drawerDescEl = panel.querySelector("[data-ext-drawer-desc]");
  var drawerContextEl = panel.querySelector("[data-ext-drawer-context]");
  var drawerTabsEl = panel.querySelector("[data-ext-drawer-tabs]");
  var drawerFormEl = panel.querySelector("[data-ext-drawer-form]");
  var drawerBodyEl = panel.querySelector("[data-ext-drawer-body]");
  if (drawerBodyEl) {
    drawerBodyEl.addEventListener("input", function () { updateLivePreview(); });
    drawerBodyEl.addEventListener("change", function () { updateLivePreview(); });
  }
  var drawerSaveBtn = panel.querySelector("[data-ext-drawer-save]");

  var catalog = [];
  var packs = [];
  var activePackFilter = "";
  var searchQuery = "";
  var activeExtId = null;
  var activeGroup = "";
  var lastTrigger = null;
  var drawerSaving = false;
  var drawerInitialValues = {};
  var lineEditorObservers = [];
  var TARGET_LABEL_MAP = {
    blog: { key: "ext.target_blog", fallback: "博客" },
    space: { key: "ext.target_space", fallback: "空间" },
    resume: { key: "ext.target_resume", fallback: "简历" }
  };

  function applySwitchSemantics(input) {
    if (!input) return;
    input.setAttribute("switch", "");
    if (!("switch" in HTMLInputElement.prototype)) {
      input.setAttribute("role", "switch");
    }
  }

  function syncSiteHeaderCount() {
    if (!siteActiveCountEl) return;
    var activeCount = 0;
    catalog.forEach(function (item) {
      if (item.enabled) activeCount += 1;
    });
    siteActiveCountEl.textContent = String(activeCount);
    siteActiveCountEl.hidden = activeCount === 0;
  }

  if (siteDialogEl) {
    if (siteOpenBtn) {
      siteOpenBtn.addEventListener("click", function () {
        hideTooltip();
        if (!siteDialogEl.open) siteDialogEl.showModal();
      });
    }
    siteDialogEl.querySelectorAll("[data-site-ext-close]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (drawerEl && !drawerEl.hidden) closeDrawer();
        siteDialogEl.close();
      });
    });
    siteDialogEl.addEventListener("cancel", function (event) {
      if (drawerEl && !drawerEl.hidden) {
        event.preventDefault();
        closeDrawer();
      }
    });
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      var isOutsideDialog = function (e) {
        var r = siteDialogEl.getBoundingClientRect();
        return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
      };
      var pressedOutside = false;
      siteDialogEl.addEventListener("pointerdown", function (e) {
        pressedOutside = (!drawerEl || drawerEl.hidden) && isOutsideDialog(e);
      });
      siteDialogEl.addEventListener("pointerup", function (e) {
        if (pressedOutside && (!drawerEl || drawerEl.hidden) && isOutsideDialog(e)) {
          siteDialogEl.close();
        }
        pressedOutside = false;
      });
    }
  }

  try {
    var catalogScript = panel.querySelector("[data-ext-catalog-json]");
    if (catalogScript && catalogScript.textContent) {
      catalog = JSON.parse(catalogScript.textContent);
    }
  } catch (e) {
    catalog = [];
  }

  try {
    var packsScript = panel.querySelector("[data-ext-packs-json]");
    if (packsScript && packsScript.textContent) {
      packs = JSON.parse(packsScript.textContent);
    }
  } catch (e) {
    packs = [];
  }

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
      window.SiteFlowToast.show(text, { type: type || "info", key: key || "", vars: vars || null });
    }
  }

  function hideTooltip() {
    if (window.SiteFlowTooltip && window.SiteFlowTooltip.hide) {
      window.SiteFlowTooltip.hide();
    }
  }

  function setHoverTip(el, text, key, vars) {
    if (!el) return;
    el.setAttribute("data-hover-tip", text || "");
    if (key) {
      el.setAttribute("data-i18n-hover-tip", key);
      if (vars) {
        el.setAttribute("data-i18n-hover-tip-vars", JSON.stringify(vars));
      } else {
        el.removeAttribute("data-i18n-hover-tip-vars");
      }
    } else {
      el.removeAttribute("data-i18n-hover-tip");
      el.removeAttribute("data-i18n-hover-tip-vars");
    }
  }

  function cloneIcon(name) {
    var tpl =
      panel.querySelector('[data-ext-icon-tpl="' + CSS.escape(name || "puzzle") + '"]') ||
      panel.querySelector('[data-ext-icon-tpl="puzzle"]');
    if (tpl && tpl.content) {
      return tpl.content.cloneNode(true);
    }
    return document.createDocumentFragment();
  }

  function cloneSkin(character) {
    var tpl = panel.querySelector('[data-mascot-skin-tpl="' + CSS.escape(character || "") + '"]');
    if (tpl && tpl.content) {
      return tpl.content.cloneNode(true);
    }
    return cloneIcon("sparkles");
  }

  function isSafePreviewUrl(url) {
    if (!url) return false;
    return (
      url.indexOf("https://") === 0 ||
      url.indexOf("http://") === 0 ||
      url.indexOf("/media/blog/") === 0 ||
      url.indexOf("/media/ext/") === 0 ||
      url.indexOf("/media/plugins/") === 0
    );
  }

  function getPackDisplayName(pack) {
    if (!pack) return "";
    if (pack.id === "official") {
      return t("ext.official_pack", null, pack.name || "SiteFlow 官方插件包");
    }
    if (getLang() === "en" && pack.name_en) return pack.name_en;
    return pack.name || pack.id || "";
  }

  function getExtDisplayName(item) {
    if (item.name_key) return t(item.name_key, null, item.name || item.id);
    if (getLang() === "en" && item.name_en) return item.name_en;
    return item.name || item.id || "";
  }

  function getExtDisplayDesc(item) {
    if (item.description_key) return t(item.description_key, null, item.description || "");
    if (getLang() === "en" && item.description_en) return item.description_en;
    return item.description || "";
  }

  function getFieldLabel(field) {
    if (field.label_key) return t(field.label_key, null, field.label_default || field.key);
    return field.label_default || field.key;
  }

  function getFieldPlaceholder(field) {
    if (field.placeholder_key) return t(field.placeholder_key, null, field.placeholder_default || "");
    return field.placeholder_default || "";
  }

  function getFieldHelp(field) {
    if (field.help_key) return t(field.help_key, null, field.help_default || "");
    return field.help_default || "";
  }

  function getOptionLabel(opt) {
    if (opt.label_key) return t(opt.label_key, null, opt.label_default || opt.value);
    return opt.label_default || opt.value;
  }

  function getGroupLabel(groupKey, groupDefault, groupId) {
    if (groupKey) return t(groupKey, null, groupDefault || groupId);
    return groupDefault || groupId;
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
      throw new Error(t("blog.network_failed", null, "网络连接失败，请重试。"));
    }
    var data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error(t("blog.request_failed", null, "请求失败") + " (HTTP " + response.status + ")");
    }
    if (!response.ok || data.ok === false) {
      var detail = data.error || (typeof data.detail === "string" ? data.detail : "");
      throw new Error(
        detail ? trError(detail) : t("blog.request_failed", null, "请求失败") + " (HTTP " + response.status + ")"
      );
    }
    return data;
  }

  async function apiForm(url, formData) {
    var response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
        body: formData
      });
    } catch (error) {
      throw new Error(t("blog.network_failed", null, "网络连接失败，请重试。"));
    }
    var data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error(t("blog.request_failed", null, "请求失败") + " (HTTP " + response.status + ")");
    }
    if (!response.ok || data.ok === false) {
      var detail = data.error || (typeof data.detail === "string" ? data.detail : "");
      throw new Error(
        detail ? trError(detail) : t("blog.request_failed", null, "请求失败") + " (HTTP " + response.status + ")"
      );
    }
    return data;
  }

  function findExt(extId) {
    for (var i = 0; i < catalog.length; i += 1) {
      if (catalog[i].id === extId) return catalog[i];
    }
    return null;
  }

  function replaceExt(updated) {
    if (!updated || !updated.id) return;
    for (var i = 0; i < catalog.length; i += 1) {
      if (catalog[i].id === updated.id) {
        catalog[i] = updated;
        return;
      }
    }
    catalog.push(updated);
  }

  function buildCardNode(item) {
    var effOn = item.effective_enabled !== undefined ? Boolean(item.effective_enabled) : Boolean(item.enabled);
    var localMode = item.local_mode || (item.installed ? (item.enabled ? "override" : "disabled") : "inherit");
    var inhOn = Boolean(item.inherited_enabled);
    var visualMode = inhOn || localMode !== "inherit" ? localMode : "disabled";
    var isBlocking = scope !== "site" && inhOn && localMode === "disabled";

    var article = document.createElement("article");
    article.className = "ext-card"
      + (effOn ? " is-enabled" : "")
      + (scope !== "site" && localMode === "inherit" && effOn ? " is-inherited" : "")
      + (isBlocking ? " is-blocked" : "");
    article.dataset.extCard = item.id;
    article.dataset.extPack = item.pack_id || "official";

    var head = document.createElement("div");
    head.className = "ext-card-head";

    var ident = document.createElement("div");
    ident.className = "ext-card-ident";

    var iconWrap = document.createElement("span");
    iconWrap.className = "ext-card-icon";
    iconWrap.appendChild(cloneIcon(item.icon || "puzzle"));
    ident.appendChild(iconWrap);

    var titleWrap = document.createElement("div");
    titleWrap.className = "ext-card-title-wrap";

    var titleRow = document.createElement("div");
    titleRow.className = "ext-card-title";
    var nameSpan = document.createElement("span");
    if (item.name_key) nameSpan.setAttribute("data-i18n", item.name_key);
    nameSpan.textContent = getExtDisplayName(item);
    titleRow.appendChild(nameSpan);

    if (item.version) {
      var verSpan = document.createElement("span");
      verSpan.className = "ext-version";
      verSpan.textContent = "v" + item.version;
      titleRow.appendChild(verSpan);
    }
    titleWrap.appendChild(titleRow);

    var subPills = document.createElement("div");
    subPills.className = "ext-card-subpills";
    if (item.pack_id && item.pack_id !== "official") {
      var packPill = document.createElement("span");
      packPill.className = "ext-pack-pill";
      packPill.textContent = item.pack_name || item.pack_id;
      subPills.appendChild(packPill);
    }
    if (scope === "site" && Array.isArray(item.targets)) {
      item.targets.forEach(function (tgt) {
        var meta = TARGET_LABEL_MAP[tgt];
        if (!meta) return;
        var tgtPill = document.createElement("span");
        tgtPill.className = "ext-target-pill";
        tgtPill.setAttribute("data-i18n", meta.key);
        tgtPill.textContent = t(meta.key, null, meta.fallback);
        subPills.appendChild(tgtPill);
      });
    }
    if (subPills.childNodes.length > 0) {
      titleWrap.appendChild(subPills);
    }
    ident.appendChild(titleWrap);
    head.appendChild(ident);

    var badge = document.createElement("span");
    if (scope === "site") {
      if (item.enabled) {
        badge.className = "ext-badge is-enabled";
        badge.setAttribute("data-i18n", "ext.site_enabled");
        badge.textContent = t("ext.site_enabled", null, "全站已启用");
      } else if (item.configured) {
        badge.className = "ext-badge is-disabled";
        badge.setAttribute("data-i18n", "blog.ext_disabled");
        badge.textContent = t("blog.ext_disabled", null, "已停用");
      } else {
        badge.className = "ext-badge is-uninstalled";
        badge.setAttribute("data-i18n", "ext.site_unset");
        badge.textContent = t("ext.site_unset", null, "未设置");
      }
    } else if (localMode === "disabled") {
      badge.className = isBlocking ? "ext-badge is-blocked" : "ext-badge is-disabled";
      badge.setAttribute("data-i18n", "ext.badge_disabled");
      badge.textContent = t("ext.badge_disabled", null, "已关闭");
    } else if (localMode === "override") {
      badge.className = "ext-badge is-override";
      badge.setAttribute("data-i18n", "ext.badge_enabled");
      badge.textContent = t("ext.badge_enabled", null, "已启用");
      if (inhOn) {
        setHoverTip(badge, t("ext.badge_override_tip", null, "本层启用并独立覆盖上级配置"), "ext.badge_override_tip");
      }
    } else if (effOn && item.source === "site") {
      badge.className = "ext-badge is-inherited";
      badge.setAttribute("data-i18n", "ext.badge_inherited_site");
      badge.textContent = t("ext.badge_inherited_site", null, "继承自全站");
    } else if (effOn && item.source === "ancestor") {
      var ancTitle = trError(item.source_title || "");
      badge.className = "ext-badge is-inherited";
      badge.dataset.extSourceAncestor = item.source_title || "";
      var ancBadgeText = t("ext.badge_inherited_ancestor", { title: ancTitle }, "继承自 " + ancTitle);
      badge.textContent = ancBadgeText;
      setHoverTip(badge, ancBadgeText);
    } else {
      badge.className = "ext-badge is-disabled";
      badge.setAttribute("data-i18n", "ext.badge_disabled");
      badge.textContent = t("ext.badge_disabled", null, "已关闭");
    }
    head.appendChild(badge);
    article.appendChild(head);

    var desc = document.createElement("p");
    desc.className = "ext-card-desc";
    if (item.description_key) desc.setAttribute("data-i18n", item.description_key);
    desc.textContent = getExtDisplayDesc(item);
    article.appendChild(desc);

    if (scope !== "site") {
      var modeGroup = document.createElement("div");
      modeGroup.className = "ext-mode-group";
      modeGroup.setAttribute("role", "radiogroup");
      modeGroup.setAttribute("aria-label", t("ext.mode_group_label", null, "插件启停与继承模式"));
      modeGroup.setAttribute("data-i18n-aria-label", "ext.mode_group_label");

      var inhAncTitle = trError(item.inherited_source_title || "");
      var inhBtn = document.createElement("button");
      inhBtn.type = "button";
      var inhActive = visualMode === "inherit";
      inhBtn.className = "ext-mode-btn" + (inhActive ? " is-active" : "") + (!inhOn ? " is-disabled" : "");
      inhBtn.setAttribute("role", "radio");
      inhBtn.setAttribute("aria-checked", inhActive ? "true" : "false");
      if (!inhOn) {
        inhBtn.setAttribute("aria-disabled", "true");
        setHoverTip(
          inhBtn,
          t("ext.tip_mode_inherit_unavailable", null, "上级未启用此插件，无法继承"),
          "ext.tip_mode_inherit_unavailable"
        );
      } else if (item.inherited_source === "site") {
        setHoverTip(
          inhBtn,
          t("ext.tip_mode_inherit_site", null, "继承来自「全站默认」的启停与配置"),
          "ext.tip_mode_inherit_site"
        );
      } else {
        setHoverTip(
          inhBtn,
          t("ext.tip_mode_inherit_ancestor", { title: inhAncTitle }, "继承来自「" + inhAncTitle + "」的启停与配置"),
          "ext.tip_mode_inherit_ancestor",
          { title: inhAncTitle }
        );
      }
      inhBtn.dataset.extMode = "inherit";
      inhBtn.dataset.extId = item.id;
      inhBtn.setAttribute("data-i18n", "ext.mode_inherit");
      inhBtn.textContent = t("ext.mode_inherit", null, "继承");
      modeGroup.appendChild(inhBtn);

      var enableBtn = document.createElement("button");
      enableBtn.type = "button";
      var enableActive = visualMode === "override";
      enableBtn.className = "ext-mode-btn" + (enableActive ? " is-active" : "");
      enableBtn.setAttribute("role", "radio");
      enableBtn.setAttribute("aria-checked", enableActive ? "true" : "false");
      enableBtn.dataset.extMode = "override";
      enableBtn.dataset.extId = item.id;
      if (localMode === "inherit") {
        enableBtn.dataset.extInstall = item.id;
      }
      var enableTipKey = inhOn ? "ext.tip_mode_enable_override" : "ext.tip_mode_enable_local";
      setHoverTip(
        enableBtn,
        t(enableTipKey, null, inhOn ? "在本层启用并独立配置，覆盖上级设置" : "在本层启用此插件"),
        enableTipKey
      );
      enableBtn.setAttribute("data-i18n", "ext.mode_override");
      enableBtn.textContent = t("ext.mode_override", null, "启用");
      modeGroup.appendChild(enableBtn);

      var offBtn = document.createElement("button");
      offBtn.type = "button";
      var offActive = visualMode === "disabled";
      offBtn.className = "ext-mode-btn" + (offActive ? " is-active" : "");
      offBtn.setAttribute("role", "radio");
      offBtn.setAttribute("aria-checked", offActive ? "true" : "false");
      offBtn.dataset.extMode = "disabled";
      offBtn.dataset.extId = item.id;
      if (isBlocking) {
        offBtn.dataset.extBlocking = "true";
      }
      var offTipKey = inhOn ? "ext.tip_mode_off_override" : "ext.tip_mode_off_default";
      setHoverTip(
        offBtn,
        t(offTipKey, null, inhOn ? "在本层关闭此插件，不继承上级" : "默认关闭，不加载此插件资源"),
        offTipKey
      );
      offBtn.setAttribute("data-i18n", "ext.mode_disabled");
      offBtn.textContent = t("ext.mode_disabled", null, "关闭");
      modeGroup.appendChild(offBtn);

      article.appendChild(modeGroup);
    }

    var footer = document.createElement("div");
    footer.className = "ext-card-footer";

    if (scope === "site") {
      var siteToggleLabel = document.createElement("label");
      siteToggleLabel.className = "ext-toggle";
      var siteCb = document.createElement("input");
      siteCb.type = "checkbox";
      applySwitchSemantics(siteCb);
      siteCb.dataset.extSiteToggle = item.id;
      siteCb.checked = Boolean(item.enabled);
      var siteToggleText = document.createElement("span");
      var siteKey = item.enabled ? "ext.site_enabled" : "ext.site_disabled";
      siteToggleText.setAttribute("data-i18n", siteKey);
      siteToggleText.textContent = t(siteKey, null, item.enabled ? "全站已启用" : "未启用");
      siteToggleLabel.appendChild(siteCb);
      siteToggleLabel.appendChild(siteToggleText);
      footer.appendChild(siteToggleLabel);

      var siteActions = document.createElement("div");
      siteActions.className = "ext-card-actions";
      if (Array.isArray(item.config_schema) && item.config_schema.length > 0) {
        var siteSettingsBtn = document.createElement("button");
        siteSettingsBtn.type = "button";
        siteSettingsBtn.className = "btn ghost icon-btn btn-sm";
        siteSettingsBtn.dataset.extOpenDrawer = item.id;
        var siteSettingsTip = t("ext.settings_tip", null, "插件设置");
        setHoverTip(siteSettingsBtn, siteSettingsTip, "ext.settings_tip");
        siteSettingsBtn.setAttribute("aria-label", siteSettingsTip);
        siteSettingsBtn.setAttribute("data-i18n-aria-label", "ext.settings_tip");
        siteSettingsBtn.appendChild(cloneIcon("sliders"));
        siteActions.appendChild(siteSettingsBtn);
      }
      if (item.configured) {
        var siteDelBtn = document.createElement("button");
        siteDelBtn.type = "button";
        siteDelBtn.className = "btn danger icon-btn btn-sm";
        siteDelBtn.dataset.extSiteDelete = item.id;
        var siteDelTip = t("ext.site_clear_default", null, "清除全站默认");
        setHoverTip(siteDelBtn, siteDelTip, "ext.site_clear_default");
        siteDelBtn.setAttribute("aria-label", siteDelTip);
        siteDelBtn.setAttribute("data-i18n-aria-label", "ext.site_clear_default");
        siteDelBtn.appendChild(cloneIcon("trash"));
        siteActions.appendChild(siteDelBtn);
      }
      footer.appendChild(siteActions);
    } else {
      var footMeta = document.createElement("div");
      footMeta.className = "ext-card-foot-meta";
      if (targetType === "space" && (localMode === "override" || localMode === "disabled")) {
        var cascadeLabel = document.createElement("label");
        cascadeLabel.className = "ext-toggle ext-cascade-toggle";
        var cascadeCb = document.createElement("input");
        cascadeCb.type = "checkbox";
        applySwitchSemantics(cascadeCb);
        cascadeCb.dataset.extCascade = item.id;
        cascadeCb.checked = Boolean(item.cascade);
        var cascadeText = document.createElement("span");
        cascadeText.setAttribute("data-i18n", "ext.cascade_children");
        cascadeText.textContent = t("ext.cascade_children", null, "向下级子项继承");
        cascadeLabel.appendChild(cascadeCb);
        cascadeLabel.appendChild(cascadeText);
        footMeta.appendChild(cascadeLabel);
      } else {
        var note = document.createElement("span");
        note.className = "ext-inherit-note";
        if (localMode === "inherit") {
          if (inhOn && item.inherited_source === "site") {
            note.setAttribute("data-i18n", "ext.inherit_hint_site");
            note.textContent = t("ext.inherit_hint_site", null, "生效来源：全站默认");
          } else if (inhOn && item.inherited_source === "ancestor") {
            var noteAncTitle = trError(item.inherited_source_title || "");
            var inhText = t("ext.inherit_hint_ancestor", { title: noteAncTitle }, "生效来源：" + noteAncTitle);
            note.textContent = inhText;
            setHoverTip(note, inhText);
          } else {
            note.setAttribute("data-i18n", "ext.inherit_hint_none");
            note.textContent = t("ext.inherit_hint_none", null, "默认关闭");
          }
        } else if (localMode === "override") {
          note.setAttribute("data-i18n", "ext.local_active_note");
          note.textContent = t("ext.local_active_note", null, "仅本页生效");
        } else {
          note.setAttribute("data-i18n", "ext.local_blocked_note");
          note.textContent = t("ext.local_blocked_note", null, "本页已关闭");
        }
        footMeta.appendChild(note);
      }
      footer.appendChild(footMeta);

      var actions = document.createElement("div");
      actions.className = "ext-card-actions";
      if (Array.isArray(item.config_schema) && item.config_schema.length > 0 && (localMode === "override" || effOn)) {
        var settingsBtn = document.createElement("button");
        settingsBtn.type = "button";
        settingsBtn.className = "btn ghost icon-btn btn-sm";
        settingsBtn.dataset.extOpenDrawer = item.id;
        var settingsTip = t("ext.settings_tip", null, "插件设置");
        setHoverTip(settingsBtn, settingsTip, "ext.settings_tip");
        settingsBtn.setAttribute("aria-label", settingsTip);
        settingsBtn.setAttribute("data-i18n-aria-label", "ext.settings_tip");
        settingsBtn.appendChild(cloneIcon("sliders"));
        actions.appendChild(settingsBtn);
      }
      if (localMode !== "inherit") {
        var resetBtn = document.createElement("button");
        resetBtn.type = "button";
        resetBtn.className = "btn ghost icon-btn btn-sm";
        resetBtn.dataset.extUninstall = item.id;
        var resetAria = t("ext.reset_to_default", null, "恢复默认");
        var resetTip = t("ext.tip_reset_to_default", null, "清除本层自定义配置并恢复默认状态");
        setHoverTip(resetBtn, resetTip, "ext.tip_reset_to_default");
        resetBtn.setAttribute("aria-label", resetAria);
        resetBtn.setAttribute("data-i18n-aria-label", "ext.reset_to_default");
        resetBtn.appendChild(cloneIcon("rotate-ccw"));
        actions.appendChild(resetBtn);
      }
      footer.appendChild(actions);
    }

    article.appendChild(footer);
    return article;
  }

  function renderCards() {
    if (!gridEl) return;
    gridEl.textContent = "";
    catalog.forEach(function (item) {
      gridEl.appendChild(buildCardNode(item));
    });
    syncSiteHeaderCount();
    applyFilters();
  }

  function updateSingleCard(item) {
    if (!gridEl || !item) return;
    var existing = gridEl.querySelector('[data-ext-card="' + CSS.escape(item.id) + '"]');
    var fresh = buildCardNode(item);
    if (existing) {
      existing.replaceWith(fresh);
    } else {
      gridEl.appendChild(fresh);
    }
    syncSiteHeaderCount();
    applyFilters();
  }

  function applyFilters() {
    if (!gridEl) return;
    var query = (searchQuery || "").trim().toLowerCase();
    var visibleCount = 0;
    var cards = gridEl.querySelectorAll("[data-ext-card]");
    cards.forEach(function (card) {
      var extId = card.dataset.extCard || "";
      var packId = card.dataset.extPack || "official";
      var item = findExt(extId);
      var matchPack = !activePackFilter || packId === activePackFilter;
      var matchSearch = true;
      if (query) {
        var haystack = [
          extId,
          packId,
          item ? getExtDisplayName(item) : "",
          item ? getExtDisplayDesc(item) : "",
          item && item.name ? item.name : "",
          item && item.description ? item.description : "",
          item && item.pack_name ? item.pack_name : ""
        ]
          .join(" ")
          .toLowerCase();
        matchSearch = haystack.indexOf(query) !== -1;
      }
      var show = matchPack && matchSearch;
      card.hidden = !show;
      if (show) visibleCount += 1;
    });
    if (filterEmptyEl) filterEmptyEl.hidden = visibleCount > 0 || catalog.length === 0;
  }

  function renderPackFilters() {
    if (!packFiltersEl) return;
    var packList = packs.slice();
    if (!packList.length) {
      var seen = {};
      catalog.forEach(function (item) {
        var pid = item.pack_id || "official";
        if (!seen[pid]) {
          seen[pid] = true;
          packList.push({ id: pid, name: item.pack_name || pid });
        }
      });
    }
    if (activePackFilter && !packList.some(function (p) { return p.id === activePackFilter; })) {
      activePackFilter = "";
    }
    if (packList.length <= 1) {
      packFiltersEl.hidden = true;
      packFiltersEl.textContent = "";
      return;
    }
    packFiltersEl.hidden = false;
    packFiltersEl.textContent = "";

    var allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "ext-filter-chip" + (activePackFilter === "" ? " is-active" : "");
    allBtn.dataset.extFilterPack = "";
    allBtn.setAttribute("data-i18n", "ext.filter_all");
    allBtn.textContent = t("ext.filter_all", null, "全部");
    packFiltersEl.appendChild(allBtn);

    packList.forEach(function (pack) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "ext-filter-chip" + (activePackFilter === pack.id ? " is-active" : "");
      chip.dataset.extFilterPack = pack.id;
      if (pack.id === "official") chip.setAttribute("data-i18n", "ext.official_pack");
      chip.textContent = getPackDisplayName(pack);
      packFiltersEl.appendChild(chip);
    });
  }

  function renderPacksList() {
    if (!packsListEl) return;
    packsListEl.textContent = "";
    packs.forEach(function (pack) {
      var isOfficial = pack.id === "official";
      var pCount = Array.isArray(pack.plugins)
        ? pack.plugins.length
        : typeof pack.plugin_count === "number"
          ? pack.plugin_count
          : 0;
      var canSync = !isOfficial && Boolean(pack.source_url || pack.url || pack.source_type === "url");

      var row = document.createElement("div");
      row.className = "ext-pack-row";
      row.dataset.packRow = pack.id;

      var info = document.createElement("div");
      info.className = "ext-pack-info";

      var iconWrap = document.createElement("span");
      iconWrap.className = "ext-pack-icon";
      iconWrap.appendChild(cloneIcon("package"));
      info.appendChild(iconWrap);

      var textWrap = document.createElement("div");
      textWrap.className = "ext-pack-text";

      var nameRow = document.createElement("div");
      nameRow.className = "ext-pack-name-row";
      var strong = document.createElement("strong");
      if (isOfficial) strong.setAttribute("data-i18n", "ext.official_pack");
      strong.textContent = getPackDisplayName(pack);
      nameRow.appendChild(strong);

      if (pack.version) {
        var ver = document.createElement("span");
        ver.className = "ext-version";
        ver.textContent = "v" + pack.version;
        nameRow.appendChild(ver);
      }

      var sourceBadge = document.createElement("span");
      sourceBadge.className = "ext-pack-source";
      var srcKey = isOfficial
        ? "ext.pack_source_official"
        : canSync
          ? "ext.pack_source_url"
          : "ext.pack_source_zip";
      sourceBadge.setAttribute("data-i18n", srcKey);
      sourceBadge.textContent = t(
        srcKey,
        null,
        isOfficial ? "官方内置" : canSync ? "URL 订阅" : "离线 ZIP"
      );
      nameRow.appendChild(sourceBadge);
      textWrap.appendChild(nameRow);

      var meta = document.createElement("div");
      meta.className = "ext-pack-meta";
      var idSpan = document.createElement("span");
      idSpan.textContent = pack.id;
      var dotSpan = document.createElement("span");
      dotSpan.textContent = "·";
      var countSpan = document.createElement("span");
      countSpan.appendChild(document.createTextNode(String(pCount) + " "));
      var unitSpan = document.createElement("span");
      unitSpan.setAttribute("data-i18n", "ext.plugins_unit");
      unitSpan.textContent = t("ext.plugins_unit", null, "个插件");
      countSpan.appendChild(unitSpan);
      meta.appendChild(idSpan);
      meta.appendChild(dotSpan);
      meta.appendChild(countSpan);
      textWrap.appendChild(meta);

      info.appendChild(textWrap);
      row.appendChild(info);

      if (!isOfficial) {
        var actions = document.createElement("div");
        actions.className = "ext-pack-actions";
        if (canSync) {
          var syncBtn = document.createElement("button");
          syncBtn.type = "button";
          syncBtn.className = "btn ghost icon-btn btn-sm";
          syncBtn.dataset.extPackSync = pack.id;
          var syncTip = t("ext.pack_sync", null, "同步更新");
          setHoverTip(syncBtn, syncTip, "ext.pack_sync");
          syncBtn.setAttribute("aria-label", syncTip);
          syncBtn.setAttribute("data-i18n-aria-label", "ext.pack_sync");
          syncBtn.appendChild(cloneIcon("refresh-cw"));
          actions.appendChild(syncBtn);
        }

        var delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "btn danger icon-btn btn-sm";
        delBtn.dataset.extPackDelete = pack.id;
        var delTip = t("ext.pack_delete", null, "退订并移除插件包");
        setHoverTip(delBtn, delTip, "ext.pack_delete");
        delBtn.setAttribute("aria-label", delTip);
        delBtn.setAttribute("data-i18n-aria-label", "ext.pack_delete");
        delBtn.appendChild(cloneIcon("trash"));
        actions.appendChild(delBtn);

        row.appendChild(actions);
      }

      packsListEl.appendChild(row);
    });
  }

  async function refreshAll(nextPacks) {
    var tasks = [apiJson("GET", base + "/extensions")];
    if (!Array.isArray(nextPacks)) {
      tasks.push(apiJson("GET", "/api/admin/plugin-packs"));
    }
    var results = await Promise.all(tasks);
    catalog = Array.isArray(results[0].extensions) ? results[0].extensions : [];
    if (Array.isArray(nextPacks)) {
      packs = nextPacks;
    } else if (results[1] && Array.isArray(results[1].packs)) {
      packs = results[1].packs;
    }
    renderPackFilters();
    renderPacksList();
    renderCards();
  }

  function updateSecretPill(pillEl, isLocalSet, isInherited, isCleared) {
    if (!pillEl) return;
    pillEl.textContent = "";
    pillEl.classList.remove("is-set", "is-cleared", "is-inherited");
    pillEl.appendChild(cloneIcon("key"));
    var span = document.createElement("span");
    if (isCleared) {
      pillEl.classList.add("is-cleared");
      span.setAttribute("data-i18n", "ext.secret_will_clear");
      span.textContent = t("ext.secret_will_clear", null, "保存后清除");
    } else if (isLocalSet) {
      pillEl.classList.add("is-set");
      span.setAttribute("data-i18n", "ext.secret_set");
      span.textContent = t("ext.secret_set", null, "已配置");
    } else if (isInherited) {
      pillEl.classList.add("is-inherited");
      span.setAttribute("data-i18n", "ext.secret_inherited");
      span.textContent = t("ext.secret_inherited", null, "继承自上级");
    } else {
      span.setAttribute("data-i18n", "ext.secret_unset");
      span.textContent = t("ext.secret_unset", null, "未配置");
    }
    pillEl.appendChild(span);
  }

  function renderDrawerContext(item) {
    if (!drawerContextEl) return;
    if (scope === "site" || !item || !item.inherited_enabled) {
      drawerContextEl.hidden = true;
      drawerContextEl.textContent = "";
      return;
    }
    var localMode = item.local_mode || "inherit";
    var inhSource = item.inherited_source || "none";
    var ancTitle = trError(item.inherited_source_title || "");
    var msg = "";
    if (localMode === "inherit") {
      msg = inhSource === "site"
        ? t("ext.drawer_ctx_inherit_site", null, "当前展示继承自「全站默认」的配置，保存后将转为本层独立配置。")
        : t("ext.drawer_ctx_inherit_ancestor", { title: ancTitle }, "当前展示继承自「" + ancTitle + "」的配置，保存后将转为本层独立配置。");
    } else if (localMode === "override") {
      msg = inhSource === "site"
        ? t("ext.drawer_ctx_override_site", null, "本层已独立配置，未修改项继续继承自「全站默认」。")
        : t("ext.drawer_ctx_override_ancestor", { title: ancTitle }, "本层已独立配置，未修改项继续继承自「" + ancTitle + "」。");
    }
    if (!msg) {
      drawerContextEl.hidden = true;
      drawerContextEl.textContent = "";
      return;
    }
    drawerContextEl.textContent = msg;
    drawerContextEl.hidden = false;
  }

  function syncDrawerPreview(fieldWrap, value) {
    var preview = fieldWrap ? fieldWrap.querySelector("[data-drawer-preview]") : null;
    if (!preview) return;
    var cleaned = (value || "").trim();
    if (isSafePreviewUrl(cleaned)) {
      preview.src = cleaned;
      preview.hidden = false;
    } else {
      preview.removeAttribute("src");
      preview.hidden = true;
    }
    updateLivePreview();
  }

  var LIVE_PREVIEW_IDS = { space_background: true, space_layout: true, resume_style: true };

  function readDrawerValue(name) {
    if (!drawerBodyEl) return "";
    var el = drawerBodyEl.querySelector('[name="' + name + '"]');
    if (!el) return "";
    if (el.type === "checkbox") return el.checked;
    return el.value;
  }

  function buildLivePreview(item) {
    var box = document.createElement("div");
    box.className = "ext-live-preview";
    box.setAttribute("data-live-preview", item.id);
    var label = document.createElement("div");
    label.className = "ext-drawer-field-label";
    label.setAttribute("data-i18n", "ext.live_preview");
    label.textContent = t("ext.live_preview", null, "实时预览");
    box.appendChild(label);
    var stage = document.createElement("div");
    stage.setAttribute("aria-hidden", "true");
    if (item.id === "space_background") {
      stage.className = "ext-lp-space";
      var layer = document.createElement("div");
      layer.className = "ext-lp-space-layer";
      var img = document.createElement("img");
      img.className = "ext-lp-space-img";
      img.alt = "";
      img.referrerPolicy = "no-referrer";
      img.hidden = true;
      stage.appendChild(layer);
      stage.appendChild(img);
      var cards = document.createElement("div");
      cards.className = "ext-lp-space-cards";
      for (var i = 0; i < 3; i++) {
        var card = document.createElement("div");
        card.className = "ext-lp-space-card";
        var line = document.createElement("span");
        card.appendChild(line);
        cards.appendChild(card);
      }
      stage.appendChild(cards);
    } else if (item.id === "space_layout") {
      stage.className = "ext-lp-layout ext-lp-mode-grid ext-lp-tilt-medium";
      var topbar = document.createElement("div");
      topbar.className = "ext-lp-layout-bar";
      var pillA = document.createElement("span");
      pillA.className = "ext-lp-layout-pill";
      var pillB = document.createElement("span");
      pillB.className = "ext-lp-layout-pill";
      topbar.appendChild(pillA);
      topbar.appendChild(pillB);
      stage.appendChild(topbar);
      var layoutCards = document.createElement("div");
      layoutCards.className = "ext-lp-layout-cards";
      for (var k = 0; k < 4; k++) {
        var lCard = document.createElement("div");
        lCard.className = "ext-lp-layout-card ext-lp-lc-" + String(k + 1);
        var thumb = document.createElement("div");
        thumb.className = "ext-lp-layout-thumb";
        var caption = document.createElement("span");
        caption.className = "ext-lp-layout-line";
        lCard.appendChild(thumb);
        lCard.appendChild(caption);
        layoutCards.appendChild(lCard);
      }
      stage.appendChild(layoutCards);
    } else {
      stage.className = "ext-lp-resume";
      var paper = document.createElement("div");
      paper.className = "ext-lp-paper";
      var name = document.createElement("div");
      name.className = "ext-lp-name";
      name.setAttribute("data-i18n", "ext.live_preview_name");
      name.textContent = t("ext.live_preview_name", null, "张三 · 产品设计师");
      paper.appendChild(name);
      ["ext.live_preview_section_exp", "ext.live_preview_section_skill"].forEach(function (key, idx) {
        var sec = document.createElement("div");
        sec.className = "ext-lp-section";
        var h = document.createElement("div");
        h.className = "ext-lp-h";
        h.setAttribute("data-i18n", key);
        h.textContent = t(key, null, idx === 0 ? "工作经历" : "技能");
        sec.appendChild(h);
        var p = document.createElement("div");
        p.className = "ext-lp-text";
        p.setAttribute("data-i18n", "ext.live_preview_text");
        p.textContent = t("ext.live_preview_text", null, "负责核心产品的体验设计与落地，推动多个版本按期上线。");
        sec.appendChild(p);
        if (idx === 1) {
          var chips = document.createElement("div");
          chips.className = "ext-lp-chips";
          ["Figma", "CSS", "UX"].forEach(function (c) {
            var chip = document.createElement("span");
            chip.className = "ext-lp-chip";
            chip.textContent = c;
            chips.appendChild(chip);
          });
          sec.appendChild(chips);
        }
        paper.appendChild(sec);
      });
      stage.appendChild(paper);
    }
    box.appendChild(stage);
    return box;
  }

  function updateLivePreview() {
    if (!drawerBodyEl) return;
    var box = drawerBodyEl.querySelector("[data-live-preview]");
    if (!box) return;
    var stage = box.lastElementChild;
    var previewId = box.getAttribute("data-live-preview");
    if (previewId === "space_background") {
      var preset = String(readDrawerValue("preset") || "none");
      stage.querySelector(".ext-lp-space-layer").className = "ext-lp-space-layer ext-lp-bg-" + preset;
      var img = stage.querySelector(".ext-lp-space-img");
      var url = String(readDrawerValue("image_url") || "").trim();
      if (isSafePreviewUrl(url)) {
        if (img.getAttribute("src") !== url) img.src = url;
        img.hidden = false;
      } else {
        img.removeAttribute("src");
        img.hidden = true;
      }
      var op = parseFloat(readDrawerValue("opacity"));
      img.style.opacity = String(isNaN(op) ? 0.2 : op);
      stage.classList.toggle("is-frosted", Boolean(readDrawerValue("frosted_cards")));
    } else if (previewId === "space_layout") {
      var mode = String(readDrawerValue("mode") || "grid");
      var tilt = String(readDrawerValue("card_tilt") || "medium");
      var showDeskControls = mode === "desk" && Boolean(readDrawerValue("show_desk_controls"));
      stage.className = [
        "ext-lp-layout",
        "ext-lp-mode-" + mode,
        "ext-lp-tilt-" + tilt,
        showDeskControls ? "has-controls" : ""
      ]
        .filter(Boolean)
        .join(" ");
    } else {
      stage.className = [
        "ext-lp-resume",
        "ext-lp-accent-" + (readDrawerValue("accent") || "indigo"),
        "ext-lp-paper-" + (readDrawerValue("paper") || "clean"),
        "ext-lp-density-" + (readDrawerValue("density") || "comfortable"),
        "ext-lp-font-" + (readDrawerValue("font_style") || "sans"),
        readDrawerValue("show_section_dividers") ? "has-dividers" : ""
      ].join(" ");
    }
  }

  function buildFieldLabelEl(tagName, field, forId) {
    var hasHelp = Boolean(field.help_default || field.help_key);
    var el = document.createElement(tagName || "span");
    el.className = "ext-drawer-field-label" + (hasHelp ? " sf-tip-label" : "");
    if (forId) el.setAttribute("for", forId);

    var textSpan = document.createElement("span");
    if (field.label_key) textSpan.setAttribute("data-i18n", field.label_key);
    textSpan.textContent = getFieldLabel(field);
    el.appendChild(textSpan);

    if (hasHelp) {
      setHoverTip(el, getFieldHelp(field), field.help_key || "");
      var iconSpan = document.createElement("span");
      iconSpan.className = "sf-tip-icon";
      iconSpan.setAttribute("aria-hidden", "true");
      iconSpan.appendChild(cloneIcon("info"));
      el.appendChild(iconSpan);
    }
    return el;
  }

  function buildDrawerField(item, field) {
    var wrap = document.createElement("div");
    wrap.className = "ext-drawer-field";

    var cfg = item.config || {};
    var defCfg = item.default_config || {};
    var val = cfg[field.key] !== undefined ? cfg[field.key] : defCfg[field.key];
    if (val === undefined || val === null) val = "";

    var kind = field.kind || "text";

    if (kind === "boolean") {
      var row = document.createElement("label");
      row.className = "ext-drawer-toggle-row";
      var labelSpan = buildFieldLabelEl("span", field);
      var toggleWrap = document.createElement("span");
      toggleWrap.className = "ext-toggle";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.name = field.key;
      cb.dataset.fieldKind = "boolean";
      cb.checked = Boolean(val);
      toggleWrap.appendChild(cb);
      row.appendChild(labelSpan);
      row.appendChild(toggleWrap);
      wrap.appendChild(row);
    } else if (kind === "character_picker") {
      var pickerLabel = buildFieldLabelEl("span", field);
      wrap.appendChild(pickerLabel);

      var hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.name = field.key;
      hiddenInput.dataset.fieldKind = "character_picker";
      hiddenInput.value = String(val);
      wrap.appendChild(hiddenInput);

      var charGrid = document.createElement("div");
      charGrid.className = "ext-char-grid";
      charGrid.setAttribute("role", "radiogroup");
      charGrid.setAttribute("aria-label", getFieldLabel(field));

      (field.options || []).forEach(function (opt) {
        var selected = String(val) === String(opt.value);
        var optBtn = document.createElement("button");
        optBtn.type = "button";
        optBtn.className = "ext-char-option" + (selected ? " is-selected" : "");
        optBtn.setAttribute("role", "radio");
        optBtn.setAttribute("aria-checked", selected ? "true" : "false");
        optBtn.dataset.charOption = opt.value;

        var checkBadge = document.createElement("span");
        checkBadge.className = "ext-char-check";
        checkBadge.appendChild(cloneIcon("check"));
        optBtn.appendChild(checkBadge);

        var thumb = document.createElement("span");
        thumb.className = "ext-char-thumb";
        thumb.appendChild(cloneSkin(opt.value));
        optBtn.appendChild(thumb);

        var nameEl = document.createElement("span");
        nameEl.className = "ext-char-name";
        if (opt.label_key) nameEl.setAttribute("data-i18n", opt.label_key);
        nameEl.textContent = getOptionLabel(opt);
        optBtn.appendChild(nameEl);

        optBtn.addEventListener("click", function () {
          hiddenInput.value = opt.value;
          charGrid.querySelectorAll("[data-char-option]").forEach(function (btn) {
            var isMatch = btn.dataset.charOption === opt.value;
            btn.classList.toggle("is-selected", isMatch);
            btn.setAttribute("aria-checked", isMatch ? "true" : "false");
          });
        });

        charGrid.appendChild(optBtn);
      });

      wrap.appendChild(charGrid);
    } else if (kind === "secret") {
      var isInheritedSecret = Boolean(item.secret_inherited && item.secret_inherited[field.key]);
      var isLocalSet = item.local_secrets_set
        ? Boolean(item.local_secrets_set[field.key])
        : (Boolean(item.secrets_set && item.secrets_set[field.key]) && !isInheritedSecret);
      var secretHead = document.createElement("div");
      secretHead.className = "ext-secret-head";
      var inputId = "ext-field-" + item.id + "-" + field.key;
      var secretLabel = buildFieldLabelEl("label", field, inputId);
      secretHead.appendChild(secretLabel);

      var pill = document.createElement("span");
      pill.className = "ext-secret-pill";
      pill.dataset.secretPill = field.key;
      updateSecretPill(pill, isLocalSet, isInheritedSecret, false);
      secretHead.appendChild(pill);
      wrap.appendChild(secretHead);

      var secretRow = document.createElement("div");
      secretRow.className = "ext-secret-row";

      var secretInput = document.createElement("input");
      secretInput.id = inputId;
      secretInput.type = "password";
      secretInput.name = field.key;
      secretInput.dataset.fieldKind = "secret";
      secretInput.dataset.secretWasSet = isLocalSet ? "1" : "0";
      secretInput.dataset.secretInherited = isInheritedSecret ? "1" : "0";
      secretInput.autocomplete = "new-password";
      secretInput.value = "";
      if (field.max_length) secretInput.maxLength = field.max_length;
      if (isLocalSet) {
        secretInput.placeholder = t("ext.secret_keep_placeholder", null, "已配置，留空保持不变");
        secretInput.setAttribute("data-i18n-placeholder", "ext.secret_keep_placeholder");
      } else if (isInheritedSecret) {
        secretInput.placeholder = t("ext.secret_inherited_placeholder", null, "已继承上级密钥，留空继续继承或输入新密钥覆盖");
        secretInput.setAttribute("data-i18n-placeholder", "ext.secret_inherited_placeholder");
      } else {
        secretInput.placeholder = getFieldPlaceholder(field) || t("ext.secret_empty_placeholder", null, "请输入密钥");
        if (field.placeholder_key) {
          secretInput.setAttribute("data-i18n-placeholder", field.placeholder_key);
        } else {
          secretInput.setAttribute("data-i18n-placeholder", "ext.secret_empty_placeholder");
        }
      }
      secretRow.appendChild(secretInput);

      var eyeBtn = document.createElement("button");
      eyeBtn.type = "button";
      eyeBtn.className = "btn ghost icon-btn btn-sm";
      var eyeTip = t("ext.secret_toggle_visibility", null, "显示 / 隐藏");
      setHoverTip(eyeBtn, eyeTip, "ext.secret_toggle_visibility");
      eyeBtn.setAttribute("aria-label", eyeTip);
      eyeBtn.setAttribute("data-i18n-aria-label", "ext.secret_toggle_visibility");
      eyeBtn.appendChild(cloneIcon("eye"));
      eyeBtn.addEventListener("click", function () {
        var reveal = secretInput.type === "password";
        secretInput.type = reveal ? "text" : "password";
        eyeBtn.textContent = "";
        eyeBtn.appendChild(cloneIcon(reveal ? "eye-off" : "eye"));
      });
      secretRow.appendChild(eyeBtn);

      var clearSecretBtn = document.createElement("button");
      clearSecretBtn.type = "button";
      clearSecretBtn.className = "btn danger icon-btn btn-sm";
      clearSecretBtn.dataset.secretClearBtn = field.key;
      var clearTip = t("ext.secret_clear", null, "清除已保存密钥");
      setHoverTip(clearSecretBtn, clearTip, "ext.secret_clear");
      clearSecretBtn.setAttribute("aria-label", clearTip);
      clearSecretBtn.setAttribute("data-i18n-aria-label", "ext.secret_clear");
      clearSecretBtn.hidden = !isLocalSet;
      clearSecretBtn.appendChild(cloneIcon("trash"));
      clearSecretBtn.addEventListener("click", function () {
        var willClear = secretInput.dataset.secretCleared !== "1";
        secretInput.dataset.secretCleared = willClear ? "1" : "0";
        if (willClear) secretInput.value = "";
        updateSecretPill(
          pill,
          secretInput.dataset.secretWasSet === "1",
          secretInput.dataset.secretInherited === "1",
          willClear
        );
        clearSecretBtn.classList.toggle("is-active", willClear);
      });
      secretRow.appendChild(clearSecretBtn);

      secretInput.addEventListener("input", function () {
        if (secretInput.value.trim()) {
          secretInput.dataset.secretCleared = "0";
          clearSecretBtn.classList.remove("is-active");
          updateSecretPill(
            pill,
            secretInput.dataset.secretWasSet === "1",
            secretInput.dataset.secretInherited === "1",
            false
          );
        }
      });

      wrap.appendChild(secretRow);
    } else if (kind === "image_url") {
      var imgInputId = "ext-field-" + item.id + "-" + field.key;
      var imgLabel = buildFieldLabelEl("label", field, imgInputId);
      wrap.appendChild(imgLabel);

      var mediaRow = document.createElement("div");
      mediaRow.className = "ext-media-row";

      var imgInput = document.createElement("input");
      imgInput.id = imgInputId;
      imgInput.type = "text";
      imgInput.name = field.key;
      imgInput.dataset.fieldKind = "image_url";
      imgInput.value = String(val);
      if (field.max_length) imgInput.maxLength = field.max_length;
      if (field.placeholder_default || field.placeholder_key) {
        imgInput.placeholder = getFieldPlaceholder(field);
      }
      if (field.placeholder_key) imgInput.setAttribute("data-i18n-placeholder", field.placeholder_key);
      imgInput.addEventListener("input", function () {
        syncDrawerPreview(wrap, imgInput.value);
      });
      mediaRow.appendChild(imgInput);

      if (scope !== "site" && field.upload_kind) {
        var uploadBtn = document.createElement("button");
        uploadBtn.type = "button";
        uploadBtn.className = "btn btn-sm";
        uploadBtn.appendChild(cloneIcon("upload"));
        var upSpan = document.createElement("span");
        upSpan.setAttribute("data-i18n", "blog.ext_upload");
        upSpan.textContent = t("blog.ext_upload", null, "上传图片");
        uploadBtn.appendChild(upSpan);
        uploadBtn.addEventListener("click", function () {
          var picker = document.createElement("input");
          picker.type = "file";
          picker.accept = field.accept || "image/*";
          picker.addEventListener("change", async function () {
            if (!picker.files || !picker.files.length) return;
            uploadBtn.disabled = true;
            upSpan.textContent = t("blog.ext_uploading", null, "上传中…");
            try {
              var fd = new FormData();
              fd.append("file", picker.files[0]);
              fd.append("kind", field.upload_kind);
              var data = await apiForm(base + "/extensions/" + encodeURIComponent(item.id) + "/media", fd);
              imgInput.value = data.url || "";
              syncDrawerPreview(wrap, imgInput.value);
              showToast(t("ext.media_uploaded", null, "图片上传成功"), "success", "ext.media_uploaded");
            } catch (error) {
              showToast(error.message, "error");
            } finally {
              uploadBtn.disabled = false;
              upSpan.textContent = t("blog.ext_upload", null, "上传图片");
            }
          });
          picker.click();
        });
        mediaRow.appendChild(uploadBtn);
      }

      var clearImgBtn = document.createElement("button");
      clearImgBtn.type = "button";
      clearImgBtn.className = "btn ghost icon-btn btn-sm";
      var clearImgTip = t("blog.ext_clear", null, "清除");
      setHoverTip(clearImgBtn, clearImgTip, "blog.ext_clear");
      clearImgBtn.setAttribute("aria-label", clearImgTip);
      clearImgBtn.setAttribute("data-i18n-aria-label", "blog.ext_clear");
      clearImgBtn.appendChild(cloneIcon("x"));
      clearImgBtn.addEventListener("click", function () {
        imgInput.value = "";
        syncDrawerPreview(wrap, "");
      });
      mediaRow.appendChild(clearImgBtn);
      wrap.appendChild(mediaRow);

      var previewImg = document.createElement("img");
      previewImg.className = "ext-media-preview";
      previewImg.dataset.drawerPreview = field.key;
      previewImg.alt = "";
      previewImg.referrerPolicy = "no-referrer";
      if (isSafePreviewUrl(String(val))) {
        previewImg.src = String(val);
        previewImg.hidden = false;
      } else {
        previewImg.hidden = true;
      }
      wrap.appendChild(previewImg);
    } else if (kind === "select") {
      var selLabel = document.createElement("label");
      selLabel.className = "ext-field";
      selLabel.appendChild(buildFieldLabelEl("span", field));

      var select = document.createElement("select");
      select.name = field.key;
      select.dataset.fieldKind = "select";
      (field.options || []).forEach(function (opt) {
        var option = document.createElement("option");
        option.value = opt.value;
        option.selected = String(val) === String(opt.value);
        if (opt.label_key) option.setAttribute("data-i18n", opt.label_key);
        option.textContent = getOptionLabel(opt);
        select.appendChild(option);
      });
      selLabel.appendChild(select);
      wrap.appendChild(selLabel);
    } else if (kind === "textarea") {
      var isList = Array.isArray(val) || Array.isArray(defCfg[field.key]);
      var taLabel = document.createElement("label");
      taLabel.className = "ext-field";
      taLabel.appendChild(buildFieldLabelEl("span", field));

      var ta = document.createElement("textarea");
      ta.name = field.key;
      ta.rows = (field.rows && field.rows > 0) ? field.rows : (isList ? 8 : 4);
      if (isList) {
        ta.className = "ext-textarea-tall ext-code-input";
        ta.setAttribute("wrap", "soft");
      } else if (ta.rows >= 6) {
        ta.className = "ext-textarea-tall";
      }
      ta.dataset.fieldKind = "textarea";
      ta.dataset.fieldList = isList ? "1" : "0";
      if (field.max_length) ta.maxLength = field.max_length;
      if (field.placeholder_default || field.placeholder_key) {
        ta.placeholder = getFieldPlaceholder(field);
      }
      if (field.placeholder_key) ta.setAttribute("data-i18n-placeholder", field.placeholder_key);
      ta.value = Array.isArray(val) ? val.join("\n") : String(val);

      if (isList) {
        var editorWrap = document.createElement("div");
        editorWrap.className = "ext-code-editor";
        editorWrap.setAttribute("data-line-editor", "");

        var gutterEl = document.createElement("div");
        gutterEl.className = "ext-line-gutter";
        gutterEl.setAttribute("data-line-gutter", "");
        gutterEl.setAttribute("aria-hidden", "true");

        var gutterInnerEl = document.createElement("div");
        gutterInnerEl.className = "ext-line-gutter-inner";
        gutterInnerEl.setAttribute("data-line-gutter-inner", "");
        gutterEl.appendChild(gutterInnerEl);

        var mirrorEl = document.createElement("div");
        mirrorEl.className = "ext-line-mirror";
        mirrorEl.setAttribute("aria-hidden", "true");

        editorWrap.appendChild(gutterEl);
        editorWrap.appendChild(ta);
        editorWrap.appendChild(mirrorEl);

        var syncLineNumbers = function () {
          var raw = ta.value || "";
          var lines = raw.split("\n");
          var computed = window.getComputedStyle(ta);
          var singleLineH = parseFloat(computed.lineHeight) || 20;
          var clientW = ta.clientWidth;
          var canMeasure = clientW > 0;

          if (canMeasure) {
            mirrorEl.style.width = clientW + "px";
            mirrorEl.style.fontFamily = computed.fontFamily;
            mirrorEl.style.fontSize = computed.fontSize;
            mirrorEl.style.fontWeight = computed.fontWeight;
            mirrorEl.style.fontStyle = computed.fontStyle;
            mirrorEl.style.lineHeight = computed.lineHeight;
            mirrorEl.style.letterSpacing = computed.letterSpacing;
            mirrorEl.style.wordSpacing = computed.wordSpacing;
            mirrorEl.style.paddingLeft = computed.paddingLeft;
            mirrorEl.style.paddingRight = computed.paddingRight;
            mirrorEl.style.paddingTop = "0";
            mirrorEl.style.paddingBottom = "0";
            mirrorEl.style.tabSize = computed.tabSize || "8";
            mirrorEl.style.border = "0";
            mirrorEl.style.boxSizing = "border-box";
          }

          gutterInnerEl.style.lineHeight = singleLineH + "px";
          gutterInnerEl.style.paddingTop = computed.paddingTop || "9px";

          var activeLine = -1;
          if (document.activeElement === ta) {
            var caret = typeof ta.selectionStart === "number" ? ta.selectionStart : 0;
            activeLine = raw.slice(0, caret).split("\n").length - 1;
          }

          var existing = gutterInnerEl.children;
          while (existing.length > lines.length) {
            gutterInnerEl.removeChild(gutterInnerEl.lastChild);
          }

          for (var i = 0; i < lines.length; i += 1) {
            var line = lines[i];
            var rowEl = existing[i];
            if (!rowEl) {
              rowEl = document.createElement("div");
              rowEl.className = "ext-line-num";
              gutterInnerEl.appendChild(rowEl);
            }
            var h = singleLineH;
            if (canMeasure) {
              mirrorEl.textContent = line.length ? line : "\u200b";
              var measured = mirrorEl.getBoundingClientRect().height;
              if (measured > 0) h = Math.max(singleLineH, measured);
            }
            rowEl.style.height = h + "px";
            var numText = String(i + 1);
            if (rowEl.textContent !== numText) rowEl.textContent = numText;
            rowEl.classList.toggle("is-comment", line.trim().charAt(0) === "#");
            rowEl.classList.toggle("is-active", i === activeLine);
          }

          gutterEl.scrollTop = ta.scrollTop;
        };

        editorWrap._syncLines = syncLineNumbers;

        ta.addEventListener("input", syncLineNumbers);
        ta.addEventListener("keyup", syncLineNumbers);
        ta.addEventListener("click", syncLineNumbers);
        ta.addEventListener("focus", syncLineNumbers);
        ta.addEventListener("blur", syncLineNumbers);
        ta.addEventListener("scroll", function () {
          gutterEl.scrollTop = ta.scrollTop;
        });

        if (typeof ResizeObserver === "function") {
          var ro = new ResizeObserver(function () {
            syncLineNumbers();
          });
          ro.observe(ta);
          lineEditorObservers.push(ro);
        }

        syncLineNumbers();
        taLabel.appendChild(editorWrap);
      } else {
        taLabel.appendChild(ta);
      }
      wrap.appendChild(taLabel);
    } else if (kind === "range") {
      var rangeLabel = document.createElement("label");
      rangeLabel.className = "ext-field";
      rangeLabel.appendChild(buildFieldLabelEl("span", field));

      var rangeRow = document.createElement("div");
      rangeRow.className = "ext-field-range";
      var rangeInput = document.createElement("input");
      rangeInput.type = "range";
      rangeInput.name = field.key;
      rangeInput.dataset.fieldKind = "range";
      if (field.min_value !== null && field.min_value !== undefined) rangeInput.min = String(field.min_value);
      if (field.max_value !== null && field.max_value !== undefined) rangeInput.max = String(field.max_value);
      if (field.step !== null && field.step !== undefined) rangeInput.step = String(field.step);
      rangeInput.value = String(val);
      var readout = document.createElement("span");
      readout.className = "ext-range-val";
      readout.textContent = String(val);
      rangeInput.addEventListener("input", function () {
        readout.textContent = rangeInput.value;
      });
      rangeRow.appendChild(rangeInput);
      rangeRow.appendChild(readout);
      rangeLabel.appendChild(rangeRow);
      wrap.appendChild(rangeLabel);
    } else if (kind === "number") {
      var numLabel = document.createElement("label");
      numLabel.className = "ext-field";
      numLabel.appendChild(buildFieldLabelEl("span", field));

      var numInput = document.createElement("input");
      numInput.type = "number";
      numInput.name = field.key;
      numInput.dataset.fieldKind = "number";
      if (field.min_value !== null && field.min_value !== undefined) numInput.min = String(field.min_value);
      if (field.max_value !== null && field.max_value !== undefined) numInput.max = String(field.max_value);
      if (field.step !== null && field.step !== undefined) numInput.step = String(field.step);
      numInput.value = String(val);
      numLabel.appendChild(numInput);
      wrap.appendChild(numLabel);
    } else {
      var textLabel = document.createElement("label");
      textLabel.className = "ext-field";
      textLabel.appendChild(buildFieldLabelEl("span", field));

      var textInput = document.createElement("input");
      textInput.type = "text";
      textInput.name = field.key;
      textInput.dataset.fieldKind = "text";
      textInput.value = String(val);
      if (field.max_length) textInput.maxLength = field.max_length;
      if (field.placeholder_default || field.placeholder_key) {
        textInput.placeholder = getFieldPlaceholder(field);
      }
      if (field.placeholder_key) textInput.setAttribute("data-i18n-placeholder", field.placeholder_key);

      if (Array.isArray(field.options) && field.options.length > 0) {
        var dlId = "ext-dl-" + item.id.replace(/[^a-zA-Z0-9_-]/g, "_") + "-" + field.key;
        var datalist = document.createElement("datalist");
        datalist.id = dlId;
        field.options.forEach(function (opt) {
          var dlOpt = document.createElement("option");
          dlOpt.value = opt.value;
          datalist.appendChild(dlOpt);
        });
        textInput.setAttribute("list", dlId);
        textLabel.appendChild(textInput);
        textLabel.appendChild(datalist);
      } else {
        textLabel.appendChild(textInput);
      }
      wrap.appendChild(textLabel);
    }

    return wrap;
  }

  function cleanupLineEditors() {
    while (lineEditorObservers.length) {
      var obs = lineEditorObservers.pop();
      try {
        obs.disconnect();
      } catch (e) {
      }
    }
  }

  function syncAllLineEditors() {
    if (!drawerBodyEl) return;
    drawerBodyEl.querySelectorAll("[data-line-editor]").forEach(function (editor) {
      if (typeof editor._syncLines === "function") {
        editor._syncLines();
      }
    });
  }

  function selectDrawerGroup(groupId) {
    activeGroup = groupId;
    if (drawerTabsEl) {
      drawerTabsEl.querySelectorAll("[data-drawer-tab]").forEach(function (tab) {
        var isMatch = tab.dataset.drawerTab === groupId;
        tab.classList.toggle("is-active", isMatch);
        tab.setAttribute("aria-selected", isMatch ? "true" : "false");
      });
    }
    if (drawerBodyEl) {
      drawerBodyEl.querySelectorAll("[data-drawer-group]").forEach(function (groupEl) {
        groupEl.hidden = groupEl.dataset.drawerGroup !== groupId;
      });
      requestAnimationFrame(syncAllLineEditors);
    }
  }

  function openDrawer(extId, triggerEl) {
    var item = findExt(extId);
    if (!item || !drawerEl || !drawerBackdropEl) return;
    hideTooltip();
    activeExtId = extId;
    lastTrigger = triggerEl || document.activeElement;

    if (drawerIconEl) {
      drawerIconEl.textContent = "";
      drawerIconEl.appendChild(cloneIcon(item.icon || "puzzle"));
    }
    if (drawerTitleEl) {
      if (item.name_key) drawerTitleEl.setAttribute("data-i18n", item.name_key);
      else drawerTitleEl.removeAttribute("data-i18n");
      drawerTitleEl.textContent = getExtDisplayName(item);
    }
    if (drawerVersionEl) {
      drawerVersionEl.textContent = item.version ? "v" + item.version : "";
    }
    if (drawerDescEl) {
      if (item.description_key) drawerDescEl.setAttribute("data-i18n", item.description_key);
      else drawerDescEl.removeAttribute("data-i18n");
      drawerDescEl.textContent = getExtDisplayDesc(item);
    }

    var schema = Array.isArray(item.config_schema) ? item.config_schema : [];
    var groups = [];
    var groupMap = {};
    schema.forEach(function (field) {
      var gid = field.group || "__default__";
      if (!groupMap[gid]) {
        groupMap[gid] = {
          id: gid,
          key: field.group_key || "",
          label: field.group_default || gid,
          fields: []
        };
        groups.push(groupMap[gid]);
      }
      groupMap[gid].fields.push(field);
    });

    cleanupLineEditors();
    if (drawerTabsEl) drawerTabsEl.textContent = "";
    if (drawerBodyEl) drawerBodyEl.textContent = "";

    var useTabs = groups.length >= 2;
    if (drawerTabsEl) drawerTabsEl.hidden = !useTabs;

    groups.forEach(function (group, idx) {
      if (useTabs && drawerTabsEl) {
        var tabBtn = document.createElement("button");
        tabBtn.type = "button";
        tabBtn.className = "ext-drawer-tab" + (idx === 0 ? " is-active" : "");
        tabBtn.setAttribute("role", "tab");
        tabBtn.setAttribute("aria-selected", idx === 0 ? "true" : "false");
        tabBtn.dataset.drawerTab = group.id;
        if (group.key) tabBtn.setAttribute("data-i18n", group.key);
        tabBtn.textContent = getGroupLabel(group.key, group.label, group.id);
        tabBtn.addEventListener("click", function () {
          selectDrawerGroup(group.id);
        });
        drawerTabsEl.appendChild(tabBtn);
      }

      var groupPanel = document.createElement("div");
      groupPanel.className = "ext-drawer-group";
      groupPanel.dataset.drawerGroup = group.id;
      if (useTabs) {
        groupPanel.setAttribute("role", "tabpanel");
        groupPanel.hidden = idx !== 0;
      }
      group.fields.forEach(function (field) {
        groupPanel.appendChild(buildDrawerField(item, field));
      });
      if (drawerBodyEl) drawerBodyEl.appendChild(groupPanel);
    });

    if (drawerBodyEl && LIVE_PREVIEW_IDS[item.id]) {
      drawerBodyEl.insertBefore(buildLivePreview(item), drawerBodyEl.firstChild);
      updateLivePreview();
    }

    renderDrawerContext(item);
    drawerInitialValues = collectDrawerFields().all;
    activeGroup = groups.length ? groups[0].id : "";

    drawerBackdropEl.hidden = false;
    drawerEl.hidden = false;
    if (!siteDialogEl) document.body.classList.add("ext-drawer-open");
    requestAnimationFrame(function () {
      drawerBackdropEl.classList.add("is-open");
      drawerEl.classList.add("is-open");
      syncAllLineEditors();
      drawerEl.focus();
    });
  }

  function closeDrawer() {
    if (!drawerEl || !drawerBackdropEl || drawerEl.hidden) return;
    hideTooltip();
    cleanupLineEditors();
    drawerEl.classList.remove("is-open");
    drawerBackdropEl.classList.remove("is-open");
    document.body.classList.remove("ext-drawer-open");
    drawerEl.hidden = true;
    drawerBackdropEl.hidden = true;
    activeExtId = null;
    drawerInitialValues = {};
    if (lastTrigger && typeof lastTrigger.focus === "function" && document.contains(lastTrigger)) {
      lastTrigger.focus();
    }
    lastTrigger = null;
  }

  function syncDrawerSecrets(updatedExt) {
    if (!drawerFormEl || !updatedExt) return;
    var localSecrets = updatedExt.local_secrets_set || updatedExt.secrets_set || {};
    var inheritedSecrets = updatedExt.secret_inherited || {};
    drawerFormEl.querySelectorAll('input[data-field-kind="secret"]').forEach(function (input) {
      var key = input.name;
      var isInherited = Boolean(inheritedSecrets[key]);
      var isLocalSet = Boolean(localSecrets[key]) && !isInherited;
      input.value = "";
      input.dataset.secretWasSet = isLocalSet ? "1" : "0";
      input.dataset.secretInherited = isInherited ? "1" : "0";
      input.dataset.secretCleared = "0";
      if (isLocalSet) {
        input.placeholder = t("ext.secret_keep_placeholder", null, "已配置，留空保持不变");
        input.setAttribute("data-i18n-placeholder", "ext.secret_keep_placeholder");
      } else if (isInherited) {
        input.placeholder = t("ext.secret_inherited_placeholder", null, "已继承上级密钥，留空继续继承或输入新密钥覆盖");
        input.setAttribute("data-i18n-placeholder", "ext.secret_inherited_placeholder");
      } else {
        input.placeholder = t("ext.secret_empty_placeholder", null, "请输入密钥");
        input.setAttribute("data-i18n-placeholder", "ext.secret_empty_placeholder");
      }
      var pill = drawerFormEl.querySelector('[data-secret-pill="' + CSS.escape(key) + '"]');
      updateSecretPill(pill, isLocalSet, isInherited, false);
      var clearBtn = drawerFormEl.querySelector('[data-secret-clear-btn="' + CSS.escape(key) + '"]');
      if (clearBtn) {
        clearBtn.hidden = !isLocalSet;
        clearBtn.classList.remove("is-active");
      }
    });
  }

  function collectDrawerFields() {
    var all = {};
    var secrets = {};
    if (!drawerFormEl) return { all: all, secrets: secrets };
    Array.from(drawerFormEl.elements).forEach(function (field) {
      if (!field.name) return;
      var kind = field.dataset.fieldKind || field.type;
      if (kind === "boolean" || field.type === "checkbox") {
        all[field.name] = Boolean(field.checked);
      } else if (kind === "range" || kind === "number") {
        all[field.name] = field.value === "" ? null : Number(field.value);
      } else if (kind === "textarea" && field.dataset.fieldList === "1") {
        all[field.name] = field.value
          .split("\n")
          .map(function (line) { return line.trim(); })
          .filter(Boolean);
      } else if (kind === "secret") {
        var secretVal = field.value.trim();
        if (secretVal) {
          secrets[field.name] = secretVal;
        } else if (field.dataset.secretCleared === "1") {
          secrets["clear_" + field.name] = true;
        }
      } else {
        all[field.name] = field.value.trim();
      }
    });
    return { all: all, secrets: secrets };
  }

  if (searchEl) {
    searchEl.addEventListener("input", function () {
      searchQuery = searchEl.value || "";
      applyFilters();
    });
  }

  if (packsToggleEl && packsPanelEl) {
    packsToggleEl.addEventListener("click", function () {
      var nextOpen = packsPanelEl.hidden;
      packsPanelEl.hidden = !nextOpen;
      packsToggleEl.setAttribute("aria-expanded", nextOpen ? "true" : "false");
      if (nextOpen && packUrlFormEl) {
        var urlInput = packUrlFormEl.querySelector('input[name="url"]');
        if (urlInput) urlInput.focus();
      }
    });
  }

  if (packUrlFormEl) {
    packUrlFormEl.addEventListener("submit", async function (event) {
      event.preventDefault();
      var urlInput = packUrlFormEl.querySelector('input[name="url"]');
      var submitBtn = packUrlFormEl.querySelector('button[type="submit"]');
      var url = urlInput ? urlInput.value.trim() : "";
      if (!url) return;
      if (submitBtn) submitBtn.disabled = true;
      showToast(t("ext.pack_subscribing", null, "正在拉取并校验插件包…"), "info", "ext.pack_subscribing");
      try {
        var data = await apiJson("POST", "/api/admin/plugin-packs", { url: url });
        if (urlInput) urlInput.value = "";
        await refreshAll(data.packs);
        showToast(t("ext.pack_subscribed", null, "插件包订阅成功"), "success", "ext.pack_subscribed");
      } catch (error) {
        showToast(error.message, "error");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  if (packUploadBtn) {
    packUploadBtn.addEventListener("click", function () {
      var picker = document.createElement("input");
      picker.type = "file";
      picker.accept = ".zip,application/zip";
      picker.addEventListener("change", async function () {
        if (!picker.files || !picker.files.length) return;
        packUploadBtn.disabled = true;
        showToast(t("ext.pack_uploading", null, "正在导入离线 ZIP 插件包…"), "info", "ext.pack_uploading");
        try {
          var fd = new FormData();
          fd.append("file", picker.files[0]);
          fd.append("replace", "true");
          var data = await apiForm("/api/admin/plugin-packs/upload", fd);
          await refreshAll(data.packs);
          showToast(t("ext.pack_uploaded", null, "离线插件包导入成功"), "success", "ext.pack_uploaded");
        } catch (error) {
          showToast(error.message, "error");
        } finally {
          packUploadBtn.disabled = false;
        }
      });
      picker.click();
    });
  }

  panel.addEventListener("click", async function (event) {
    var filterChip = event.target.closest("[data-ext-filter-pack]");
    if (filterChip) {
      activePackFilter = filterChip.dataset.extFilterPack || "";
      renderPackFilters();
      applyFilters();
      return;
    }

    var modeBtn = event.target.closest("[data-ext-mode]");
    if (modeBtn && scope !== "site") {
      if (modeBtn.getAttribute("aria-disabled") === "true") return;
      var modeExtId = modeBtn.dataset.extId;
      var nextMode = modeBtn.dataset.extMode;
      var curItem = findExt(modeExtId);
      if (curItem) {
        var curVisualMode = curItem.inherited_enabled || curItem.local_mode !== "inherit"
          ? curItem.local_mode
          : "disabled";
        if (curVisualMode === nextMode) return;
      }
      hideTooltip();
      var group = modeBtn.closest(".ext-mode-group");
      var groupBtns = group ? Array.from(group.querySelectorAll("button")) : [modeBtn];
      groupBtns.forEach(function (b) { b.disabled = true; });
      try {
        var modeRes = await apiJson("PUT", base + "/extensions/" + encodeURIComponent(modeExtId), {
          mode: nextMode
        });
        if (modeRes.extension) {
          replaceExt(modeRes.extension);
          updateSingleCard(modeRes.extension);
          if (activeExtId === modeExtId) {
            renderDrawerContext(modeRes.extension);
            syncDrawerSecrets(modeRes.extension);
          }
        } else {
          await refreshAll();
        }
        var statusKey = nextMode === "override"
          ? "ext.mode_saved_override"
          : nextMode === "disabled"
            ? "ext.mode_saved_disabled"
            : "ext.mode_saved_inherit";
        showToast(t(statusKey), "success", statusKey);
      } catch (error) {
        showToast(error.message, "error");
        groupBtns.forEach(function (b) { b.disabled = false; });
      }
      return;
    }

    var siteDelBtn = event.target.closest("[data-ext-site-delete]");
    if (siteDelBtn && scope === "site") {
      if (!confirm(t("ext.site_confirm_clear", null, "确定清除该插件的全站默认设置？子页面将不再从全站继承该插件。"))) return;
      hideTooltip();
      var siteDelId = siteDelBtn.dataset.extSiteDelete;
      siteDelBtn.disabled = true;
      try {
        var siteDelRes = await apiJson("DELETE", base + "/extensions/" + encodeURIComponent(siteDelId));
        if (activeExtId === siteDelId) closeDrawer();
        if (siteDelRes.extension) {
          replaceExt(siteDelRes.extension);
          updateSingleCard(siteDelRes.extension);
        } else {
          await refreshAll();
        }
        showToast(t("ext.site_cleared", null, "已清除全站默认设置"), "success", "ext.site_cleared");
      } catch (error) {
        showToast(error.message, "error");
        siteDelBtn.disabled = false;
      }
      return;
    }

    var uninstallBtn = event.target.closest("[data-ext-uninstall]");
    if (uninstallBtn) {
      if (!confirm(t("ext.confirm_reset_default", null, "确定清除本层配置并恢复默认状态？"))) return;
      hideTooltip();
      var uninstallId = uninstallBtn.dataset.extUninstall;
      uninstallBtn.disabled = true;
      try {
        var delRes = await apiJson("DELETE", base + "/extensions/" + encodeURIComponent(uninstallId));
        if (activeExtId === uninstallId) closeDrawer();
        if (delRes.extension) {
          replaceExt(delRes.extension);
          updateSingleCard(delRes.extension);
        } else {
          await refreshAll();
        }
        showToast(t("ext.reset_done", null, "已恢复默认状态"), "success", "ext.reset_done");
      } catch (error) {
        showToast(error.message, "error");
        uninstallBtn.disabled = false;
      }
      return;
    }

    var openBtn = event.target.closest("[data-ext-open-drawer]");
    if (openBtn) {
      openDrawer(openBtn.dataset.extOpenDrawer, openBtn);
      return;
    }

    var closeBtn = event.target.closest("[data-ext-drawer-close]");
    if (closeBtn) {
      closeDrawer();
      return;
    }

    var syncBtn = event.target.closest("[data-ext-pack-sync]");
    if (syncBtn) {
      var syncId = syncBtn.dataset.extPackSync;
      syncBtn.disabled = true;
      syncBtn.classList.add("is-spinning");
      showToast(t("ext.pack_syncing", null, "正在同步插件包…"), "info", "ext.pack_syncing");
      try {
        var syncData = await apiJson("POST", "/api/admin/plugin-packs/" + encodeURIComponent(syncId) + "/sync");
        await refreshAll(syncData.packs);
        showToast(t("ext.pack_synced", null, "插件包已同步至最新版本"), "success", "ext.pack_synced");
      } catch (error) {
        showToast(error.message, "error");
      } finally {
        syncBtn.disabled = false;
        syncBtn.classList.remove("is-spinning");
      }
      return;
    }

    var packDelBtn = event.target.closest("[data-ext-pack-delete]");
    if (packDelBtn) {
      if (!confirm(t("ext.pack_confirm_delete", null, "确定退订并移除该插件包？将同时清理所有项目对该包插件的引用。"))) {
        return;
      }
      hideTooltip();
      var delPackId = packDelBtn.dataset.extPackDelete;
      packDelBtn.disabled = true;
      try {
        var packDelData = await apiJson("DELETE", "/api/admin/plugin-packs/" + encodeURIComponent(delPackId));
        if (activeExtId && activeExtId.indexOf(delPackId + ".") === 0) closeDrawer();
        if (activePackFilter === delPackId) activePackFilter = "";
        await refreshAll(packDelData.packs);
        showToast(t("ext.pack_deleted", null, "已退订并移除插件包"), "success", "ext.pack_deleted");
      } catch (error) {
        showToast(error.message, "error");
        packDelBtn.disabled = false;
      }
    }
  });

  if (drawerBackdropEl) {
    drawerBackdropEl.addEventListener("click", closeDrawer);
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawerEl && !drawerEl.hidden && (!siteDialogEl || !siteDialogEl.open)) {
      event.preventDefault();
      closeDrawer();
    }
  });

  panel.addEventListener("change", async function (event) {
    var siteToggle = event.target.closest("[data-ext-site-toggle]");
    if (siteToggle && scope === "site") {
      var siteExtId = siteToggle.dataset.extSiteToggle;
      var siteEnabled = Boolean(siteToggle.checked);
      siteToggle.disabled = true;
      try {
        var siteRes = await apiJson("PUT", base + "/extensions/" + encodeURIComponent(siteExtId), {
          enabled: siteEnabled
        });
        if (siteRes.extension) {
          replaceExt(siteRes.extension);
          updateSingleCard(siteRes.extension);
        } else {
          await refreshAll();
        }
        var siteToastKey = siteEnabled ? "ext.site_saved_on" : "ext.site_saved_off";
        showToast(t(siteToastKey), "success", siteToastKey);
      } catch (error) {
        siteToggle.checked = !siteEnabled;
        siteToggle.disabled = false;
        showToast(error.message, "error");
      }
      return;
    }

    var cascadeToggle = event.target.closest("[data-ext-cascade]");
    if (cascadeToggle && scope !== "site") {
      var casExtId = cascadeToggle.dataset.extCascade;
      var nextCascade = Boolean(cascadeToggle.checked);
      if (nextCascade) {
        if (!confirm(t("ext.confirm_cascade_on", null, "开启后将同步影响下级处于继承状态的子空间与页面配置，确定开启？"))) {
          cascadeToggle.checked = false;
          return;
        }
      }
      cascadeToggle.disabled = true;
      try {
        var casRes = await apiJson("PATCH", base + "/extensions/" + encodeURIComponent(casExtId), {
          cascade: nextCascade
        });
        if (casRes.extension) {
          replaceExt(casRes.extension);
          updateSingleCard(casRes.extension);
        } else {
          await refreshAll();
        }
        var casKey = nextCascade ? "ext.cascade_saved_on" : "ext.cascade_saved_off";
        showToast(t(casKey), "success", casKey);
      } catch (error) {
        cascadeToggle.checked = !nextCascade;
        cascadeToggle.disabled = false;
        showToast(error.message, "error");
      }
      return;
    }

    var toggle = event.target.closest("[data-ext-toggle]");
    if (!toggle) return;
    var extId = toggle.dataset.extToggle;
    var nextEnabled = Boolean(toggle.checked);
    toggle.disabled = true;
    try {
      var res = await apiJson("PATCH", base + "/extensions/" + encodeURIComponent(extId), {
        enabled: nextEnabled
      });
      if (res.extension) {
        replaceExt(res.extension);
        updateSingleCard(res.extension);
      } else {
        await refreshAll();
      }
      var toggleKey = nextEnabled ? "ext.mode_saved_override" : "ext.mode_saved_disabled";
      showToast(t(toggleKey), "success", toggleKey);
    } catch (error) {
      toggle.checked = !nextEnabled;
      toggle.disabled = false;
      showToast(error.message, "error");
    }
  });

  if (drawerFormEl) {
    drawerFormEl.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (!activeExtId || drawerSaving) return;
      var curItem = findExt(activeExtId);
      drawerSaving = true;
      if (drawerSaveBtn) drawerSaveBtn.disabled = true;

      var collected = collectDrawerFields();
      var config = {};
      if (scope !== "site" && curItem && curItem.inherited_enabled) {
        var existingLocal = curItem.local_config || {};
        Object.keys(collected.all).forEach(function (k) {
          var prevVal = drawerInitialValues[k];
          var curVal = collected.all[k];
          var changed = JSON.stringify(prevVal) !== JSON.stringify(curVal);
          if (changed || Object.prototype.hasOwnProperty.call(existingLocal, k)) {
            config[k] = curVal;
          }
        });
      } else {
        Object.keys(collected.all).forEach(function (k) {
          config[k] = collected.all[k];
        });
      }
      Object.keys(collected.secrets).forEach(function (k) {
        config[k] = collected.secrets[k];
      });

      var payload = scope === "site"
        ? { enabled: curItem && curItem.configured ? Boolean(curItem.enabled) : true, config: config }
        : { mode: "override", config: config };

      try {
        var res = await apiJson("PUT", base + "/extensions/" + encodeURIComponent(activeExtId), payload);
        if (res.extension) {
          replaceExt(res.extension);
          updateSingleCard(res.extension);
          renderDrawerContext(res.extension);
          syncDrawerSecrets(res.extension);
          drawerInitialValues = collectDrawerFields().all;
        }
        showToast(t("blog.ext_saved", null, "配置已保存"), "success", "blog.ext_saved");
      } catch (error) {
        showToast(t("resume.save_failed", null, "保存失败") + "：" + error.message, "error");
      } finally {
        drawerSaving = false;
        if (drawerSaveBtn) drawerSaveBtn.disabled = false;
      }
    });
  }

  window.addEventListener("siteflow:langchange", function () {
    renderPackFilters();
    renderPacksList();
    renderCards();
    if (activeExtId) {
      var item = findExt(activeExtId);
      if (item && drawerTitleEl) drawerTitleEl.textContent = getExtDisplayName(item);
      if (item && drawerDescEl) drawerDescEl.textContent = getExtDisplayDesc(item);
      if (item) {
        renderDrawerContext(item);
        syncDrawerSecrets(item);
      }
    }
  });

  panel.querySelectorAll('input[type="checkbox"][switch]').forEach(applySwitchSemantics);
  renderPackFilters();
  renderPacksList();
  renderCards();
})();
