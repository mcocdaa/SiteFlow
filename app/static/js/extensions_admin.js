(function () {
  "use strict";

  var panel = document.querySelector("[data-ext-panel]");
  if (!panel) return;

  var projectId = panel.dataset.projectId || "";
  var base = "/api/admin/projects/" + encodeURIComponent(projectId);
  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var csrf = csrfMeta ? csrfMeta.content : "";

  var gridEl = panel.querySelector("[data-ext-grid]");
  var countEl = panel.querySelector("[data-ext-count]");
  var searchEl = panel.querySelector("[data-ext-search]");
  var packFiltersEl = panel.querySelector("[data-ext-pack-filters]");
  var filterEmptyEl = panel.querySelector("[data-ext-filter-empty]");
  var panelStatusEl = panel.querySelector("[data-ext-panel-status]");
  var packsToggleEl = panel.querySelector("[data-ext-packs-toggle]");
  var packsPanelEl = panel.querySelector("[data-ext-packs-panel]");
  var packUrlFormEl = panel.querySelector("[data-ext-pack-url-form]");
  var packUploadBtn = panel.querySelector("[data-ext-pack-upload]");
  var packStatusEl = panel.querySelector("[data-ext-pack-status]");
  var packsListEl = panel.querySelector("[data-ext-packs-list]");

  var drawerBackdropEl = panel.querySelector("[data-ext-drawer-backdrop]");
  var drawerEl = panel.querySelector("[data-ext-drawer]");
  var drawerIconEl = panel.querySelector("[data-ext-drawer-icon]");
  var drawerTitleEl = panel.querySelector("[data-ext-drawer-title]");
  var drawerVersionEl = panel.querySelector("[data-ext-drawer-version]");
  var drawerDescEl = panel.querySelector("[data-ext-drawer-desc]");
  var drawerTabsEl = panel.querySelector("[data-ext-drawer-tabs]");
  var drawerFormEl = panel.querySelector("[data-ext-drawer-form]");
  var drawerBodyEl = panel.querySelector("[data-ext-drawer-body]");
  if (drawerBodyEl) {
    drawerBodyEl.addEventListener("input", function () { updateLivePreview(); });
    drawerBodyEl.addEventListener("change", function () { updateLivePreview(); });
  }
  var drawerStatusEl = panel.querySelector("[data-ext-drawer-status]");
  var drawerSaveBtn = panel.querySelector("[data-ext-drawer-save]");

  var catalog = [];
  var packs = [];
  var activePackFilter = "";
  var searchQuery = "";
  var activeExtId = null;
  var activeGroup = "";
  var lastTrigger = null;
  var drawerSaving = false;
  var lineEditorObservers = [];

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

  function setStatus(el, text, isError, statusKey) {
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("is-error", Boolean(isError));
    el.setAttribute("role", isError ? "alert" : "status");
    if (statusKey) {
      el.dataset.statusKey = statusKey;
    } else {
      delete el.dataset.statusKey;
    }
  }

  function refreshStatusLang(el) {
    if (!el) return;
    if (el.dataset.statusKey) {
      el.textContent = t(el.dataset.statusKey);
    } else if (el.textContent) {
      el.textContent = trError(el.textContent);
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
    var article = document.createElement("article");
    article.className = "ext-card" + (item.installed && item.enabled ? " is-enabled" : "");
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

    if (item.pack_id && item.pack_id !== "official") {
      var packPill = document.createElement("span");
      packPill.className = "ext-pack-pill";
      packPill.textContent = item.pack_name || item.pack_id;
      titleWrap.appendChild(packPill);
    }
    ident.appendChild(titleWrap);
    head.appendChild(ident);

    var badge = document.createElement("span");
    if (item.installed && item.enabled) {
      badge.className = "ext-badge is-enabled";
      badge.setAttribute("data-i18n", "blog.ext_enabled");
      badge.textContent = t("blog.ext_enabled", null, "已启用");
    } else if (item.installed) {
      badge.className = "ext-badge is-disabled";
      badge.setAttribute("data-i18n", "blog.ext_disabled");
      badge.textContent = t("blog.ext_disabled", null, "已停用");
    } else {
      badge.className = "ext-badge is-uninstalled";
      badge.setAttribute("data-i18n", "blog.ext_not_installed");
      badge.textContent = t("blog.ext_not_installed", null, "未安装");
    }
    head.appendChild(badge);
    article.appendChild(head);

    var desc = document.createElement("p");
    desc.className = "ext-card-desc";
    if (item.description_key) desc.setAttribute("data-i18n", item.description_key);
    desc.textContent = getExtDisplayDesc(item);
    article.appendChild(desc);

    var footer = document.createElement("div");
    footer.className = "ext-card-footer";

    if (item.installed) {
      var toggleLabel = document.createElement("label");
      toggleLabel.className = "ext-toggle";
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.extToggle = item.id;
      checkbox.checked = Boolean(item.enabled);
      var toggleText = document.createElement("span");
      var stateKey = item.enabled ? "blog.ext_enabled" : "blog.ext_disabled";
      toggleText.setAttribute("data-i18n", stateKey);
      toggleText.textContent = t(stateKey, null, item.enabled ? "已启用" : "已停用");
      toggleLabel.appendChild(checkbox);
      toggleLabel.appendChild(toggleText);
      footer.appendChild(toggleLabel);

      var actions = document.createElement("div");
      actions.className = "ext-card-actions";
      if (Array.isArray(item.config_schema) && item.config_schema.length > 0) {
        var settingsBtn = document.createElement("button");
        settingsBtn.type = "button";
        settingsBtn.className = "btn ghost icon-btn btn-sm";
        settingsBtn.dataset.extOpenDrawer = item.id;
        var settingsTip = t("ext.settings_tip", null, "插件设置");
        settingsBtn.setAttribute("data-tip", settingsTip);
        settingsBtn.setAttribute("data-i18n-tip", "ext.settings_tip");
        settingsBtn.setAttribute("aria-label", settingsTip);
        settingsBtn.setAttribute("data-i18n-aria-label", "ext.settings_tip");
        settingsBtn.appendChild(cloneIcon("sliders"));
        actions.appendChild(settingsBtn);
      }

      var uninstallBtn = document.createElement("button");
      uninstallBtn.type = "button";
      uninstallBtn.className = "btn danger icon-btn btn-sm";
      uninstallBtn.dataset.extUninstall = item.id;
      var uninstallTip = t("blog.ext_uninstall", null, "卸载");
      uninstallBtn.setAttribute("data-tip", uninstallTip);
      uninstallBtn.setAttribute("data-i18n-tip", "blog.ext_uninstall");
      uninstallBtn.setAttribute("aria-label", uninstallTip);
      uninstallBtn.setAttribute("data-i18n-aria-label", "blog.ext_uninstall");
      uninstallBtn.appendChild(cloneIcon("trash"));
      actions.appendChild(uninstallBtn);
      footer.appendChild(actions);
    } else {
      var installBtn = document.createElement("button");
      installBtn.type = "button";
      installBtn.className = "btn primary btn-sm ext-install-btn";
      installBtn.dataset.extInstall = item.id;
      installBtn.appendChild(cloneIcon("download"));
      var installSpan = document.createElement("span");
      installSpan.setAttribute("data-i18n", "blog.ext_install");
      installSpan.textContent = t("blog.ext_install", null, "安装");
      installBtn.appendChild(installSpan);
      footer.appendChild(installBtn);
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
    if (countEl) countEl.textContent = String(visibleCount);
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
          syncBtn.setAttribute("data-tip", syncTip);
          syncBtn.setAttribute("data-i18n-tip", "ext.pack_sync");
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
        delBtn.setAttribute("data-tip", delTip);
        delBtn.setAttribute("data-i18n-tip", "ext.pack_delete");
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

  function updateSecretPill(pillEl, isSet, isCleared) {
    if (!pillEl) return;
    pillEl.textContent = "";
    pillEl.classList.remove("is-set", "is-cleared");
    pillEl.appendChild(cloneIcon("key"));
    var span = document.createElement("span");
    if (isCleared) {
      pillEl.classList.add("is-cleared");
      span.setAttribute("data-i18n", "ext.secret_will_clear");
      span.textContent = t("ext.secret_will_clear", null, "保存后清除");
    } else if (isSet) {
      pillEl.classList.add("is-set");
      span.setAttribute("data-i18n", "ext.secret_set");
      span.textContent = t("ext.secret_set", null, "已配置");
    } else {
      span.setAttribute("data-i18n", "ext.secret_unset");
      span.textContent = t("ext.secret_unset", null, "未配置");
    }
    pillEl.appendChild(span);
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

  var LIVE_PREVIEW_IDS = { space_background: true, resume_style: true };

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
    if (box.getAttribute("data-live-preview") === "space_background") {
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
      var labelSpan = document.createElement("span");
      labelSpan.className = "ext-drawer-field-label";
      if (field.label_key) labelSpan.setAttribute("data-i18n", field.label_key);
      labelSpan.textContent = getFieldLabel(field);
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
      var pickerLabel = document.createElement("span");
      pickerLabel.className = "ext-drawer-field-label";
      if (field.label_key) pickerLabel.setAttribute("data-i18n", field.label_key);
      pickerLabel.textContent = getFieldLabel(field);
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
      var isSet = Boolean(item.secrets_set && item.secrets_set[field.key]);
      var secretHead = document.createElement("div");
      secretHead.className = "ext-secret-head";
      var secretLabel = document.createElement("label");
      secretLabel.className = "ext-drawer-field-label";
      var inputId = "ext-field-" + item.id + "-" + field.key;
      secretLabel.setAttribute("for", inputId);
      if (field.label_key) secretLabel.setAttribute("data-i18n", field.label_key);
      secretLabel.textContent = getFieldLabel(field);
      secretHead.appendChild(secretLabel);

      var pill = document.createElement("span");
      pill.className = "ext-secret-pill";
      pill.dataset.secretPill = field.key;
      updateSecretPill(pill, isSet, false);
      secretHead.appendChild(pill);
      wrap.appendChild(secretHead);

      var secretRow = document.createElement("div");
      secretRow.className = "ext-secret-row";

      var secretInput = document.createElement("input");
      secretInput.id = inputId;
      secretInput.type = "password";
      secretInput.name = field.key;
      secretInput.dataset.fieldKind = "secret";
      secretInput.dataset.secretWasSet = isSet ? "1" : "0";
      secretInput.autocomplete = "new-password";
      secretInput.value = "";
      if (field.max_length) secretInput.maxLength = field.max_length;
      if (isSet) {
        secretInput.placeholder = t("ext.secret_keep_placeholder", null, "已配置，留空保持不变");
        secretInput.setAttribute("data-i18n-placeholder", "ext.secret_keep_placeholder");
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
      eyeBtn.setAttribute("data-tip", eyeTip);
      eyeBtn.setAttribute("data-i18n-tip", "ext.secret_toggle_visibility");
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
      clearSecretBtn.setAttribute("data-tip", clearTip);
      clearSecretBtn.setAttribute("data-i18n-tip", "ext.secret_clear");
      clearSecretBtn.setAttribute("aria-label", clearTip);
      clearSecretBtn.setAttribute("data-i18n-aria-label", "ext.secret_clear");
      clearSecretBtn.hidden = !isSet;
      clearSecretBtn.appendChild(cloneIcon("trash"));
      clearSecretBtn.addEventListener("click", function () {
        var willClear = secretInput.dataset.secretCleared !== "1";
        secretInput.dataset.secretCleared = willClear ? "1" : "0";
        if (willClear) secretInput.value = "";
        updateSecretPill(pill, secretInput.dataset.secretWasSet === "1", willClear);
        clearSecretBtn.classList.toggle("is-active", willClear);
      });
      secretRow.appendChild(clearSecretBtn);

      secretInput.addEventListener("input", function () {
        if (secretInput.value.trim()) {
          secretInput.dataset.secretCleared = "0";
          clearSecretBtn.classList.remove("is-active");
          updateSecretPill(pill, secretInput.dataset.secretWasSet === "1", false);
        }
      });

      wrap.appendChild(secretRow);
    } else if (kind === "image_url") {
      var imgLabel = document.createElement("label");
      imgLabel.className = "ext-drawer-field-label";
      var imgInputId = "ext-field-" + item.id + "-" + field.key;
      imgLabel.setAttribute("for", imgInputId);
      if (field.label_key) imgLabel.setAttribute("data-i18n", field.label_key);
      imgLabel.textContent = getFieldLabel(field);
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

      if (field.upload_kind) {
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
              setStatus(drawerStatusEl, "", false);
            } catch (error) {
              setStatus(drawerStatusEl, error.message, true);
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
      clearImgBtn.setAttribute("data-tip", clearImgTip);
      clearImgBtn.setAttribute("data-i18n-tip", "blog.ext_clear");
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
      var selText = document.createElement("span");
      selText.className = "ext-drawer-field-label";
      if (field.label_key) selText.setAttribute("data-i18n", field.label_key);
      selText.textContent = getFieldLabel(field);
      selLabel.appendChild(selText);

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
      var taText = document.createElement("span");
      taText.className = "ext-drawer-field-label";
      if (field.label_key) taText.setAttribute("data-i18n", field.label_key);
      taText.textContent = getFieldLabel(field);
      taLabel.appendChild(taText);

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
      var rangeText = document.createElement("span");
      rangeText.className = "ext-drawer-field-label";
      if (field.label_key) rangeText.setAttribute("data-i18n", field.label_key);
      rangeText.textContent = getFieldLabel(field);
      rangeLabel.appendChild(rangeText);

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
      var numText = document.createElement("span");
      numText.className = "ext-drawer-field-label";
      if (field.label_key) numText.setAttribute("data-i18n", field.label_key);
      numText.textContent = getFieldLabel(field);
      numLabel.appendChild(numText);

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
      var textSpan = document.createElement("span");
      textSpan.className = "ext-drawer-field-label";
      if (field.label_key) textSpan.setAttribute("data-i18n", field.label_key);
      textSpan.textContent = getFieldLabel(field);
      textLabel.appendChild(textSpan);

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

    if (field.help_default || field.help_key) {
      var help = document.createElement("span");
      help.className = "ext-field-help";
      if (field.help_key) help.setAttribute("data-i18n", field.help_key);
      help.textContent = getFieldHelp(field);
      wrap.appendChild(help);
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
    activeExtId = extId;
    lastTrigger = triggerEl || document.activeElement;
    setStatus(drawerStatusEl, "", false);

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

    activeGroup = groups.length ? groups[0].id : "";

    drawerBackdropEl.hidden = false;
    drawerEl.hidden = false;
    document.body.classList.add("ext-drawer-open");
    requestAnimationFrame(function () {
      drawerBackdropEl.classList.add("is-open");
      drawerEl.classList.add("is-open");
      syncAllLineEditors();
      drawerEl.focus();
    });
  }

  function closeDrawer() {
    if (!drawerEl || !drawerBackdropEl || drawerEl.hidden) return;
    cleanupLineEditors();
    drawerEl.classList.remove("is-open");
    drawerBackdropEl.classList.remove("is-open");
    document.body.classList.remove("ext-drawer-open");
    drawerEl.hidden = true;
    drawerBackdropEl.hidden = true;
    activeExtId = null;
    setStatus(drawerStatusEl, "", false);
    if (lastTrigger && typeof lastTrigger.focus === "function" && document.contains(lastTrigger)) {
      lastTrigger.focus();
    }
    lastTrigger = null;
  }

  function syncDrawerSecrets(updatedExt) {
    if (!drawerFormEl || !updatedExt) return;
    var secretsSet = updatedExt.secrets_set || {};
    drawerFormEl.querySelectorAll('input[data-field-kind="secret"]').forEach(function (input) {
      var key = input.name;
      var isSet = Boolean(secretsSet[key]);
      input.value = "";
      input.dataset.secretWasSet = isSet ? "1" : "0";
      input.dataset.secretCleared = "0";
      if (isSet) {
        input.placeholder = t("ext.secret_keep_placeholder", null, "已配置，留空保持不变");
        input.setAttribute("data-i18n-placeholder", "ext.secret_keep_placeholder");
      } else {
        input.placeholder = t("ext.secret_empty_placeholder", null, "请输入密钥");
        input.setAttribute("data-i18n-placeholder", "ext.secret_empty_placeholder");
      }
      var pill = drawerFormEl.querySelector('[data-secret-pill="' + CSS.escape(key) + '"]');
      updateSecretPill(pill, isSet, false);
      var clearBtn = drawerFormEl.querySelector('[data-secret-clear-btn="' + CSS.escape(key) + '"]');
      if (clearBtn) {
        clearBtn.hidden = !isSet;
        clearBtn.classList.remove("is-active");
      }
    });
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
      setStatus(packStatusEl, t("ext.pack_subscribing", null, "正在拉取并校验插件包…"), false, "ext.pack_subscribing");
      try {
        var data = await apiJson("POST", "/api/admin/plugin-packs", { url: url });
        if (urlInput) urlInput.value = "";
        await refreshAll(data.packs);
        setStatus(packStatusEl, t("ext.pack_subscribed", null, "插件包订阅成功"), false, "ext.pack_subscribed");
      } catch (error) {
        setStatus(packStatusEl, error.message, true);
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
        setStatus(packStatusEl, t("ext.pack_uploading", null, "正在导入离线 ZIP 插件包…"), false, "ext.pack_uploading");
        try {
          var fd = new FormData();
          fd.append("file", picker.files[0]);
          fd.append("replace", "true");
          var data = await apiForm("/api/admin/plugin-packs/upload", fd);
          await refreshAll(data.packs);
          setStatus(packStatusEl, t("ext.pack_uploaded", null, "离线插件包导入成功"), false, "ext.pack_uploaded");
        } catch (error) {
          setStatus(packStatusEl, error.message, true);
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

    var installBtn = event.target.closest("[data-ext-install]");
    if (installBtn) {
      var installId = installBtn.dataset.extInstall;
      installBtn.disabled = true;
      setStatus(panelStatusEl, t("ext.installing", null, "正在安装插件…"), false, "ext.installing");
      try {
        var res = await apiJson("POST", base + "/extensions/" + encodeURIComponent(installId) + "/install", {
          enabled: true
        });
        if (res.extension) {
          replaceExt(res.extension);
          updateSingleCard(res.extension);
        } else {
          await refreshAll();
        }
        setStatus(panelStatusEl, t("ext.installed", null, "插件已安装并启用"), false, "ext.installed");
      } catch (error) {
        setStatus(panelStatusEl, error.message, true);
        installBtn.disabled = false;
      }
      return;
    }

    var uninstallBtn = event.target.closest("[data-ext-uninstall]");
    if (uninstallBtn) {
      if (!confirm(t("blog.ext_confirm_uninstall", null, "确定卸载该插件？插件配置将被移除。"))) return;
      var uninstallId = uninstallBtn.dataset.extUninstall;
      uninstallBtn.disabled = true;
      setStatus(panelStatusEl, t("ext.uninstalling", null, "正在卸载插件…"), false, "ext.uninstalling");
      try {
        var delRes = await apiJson("DELETE", base + "/extensions/" + encodeURIComponent(uninstallId));
        if (activeExtId === uninstallId) closeDrawer();
        if (delRes.extension) {
          replaceExt(delRes.extension);
          updateSingleCard(delRes.extension);
        } else {
          await refreshAll();
        }
        setStatus(panelStatusEl, t("ext.uninstalled", null, "插件已卸载"), false, "ext.uninstalled");
      } catch (error) {
        setStatus(panelStatusEl, error.message, true);
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
      setStatus(packStatusEl, t("ext.pack_syncing", null, "正在同步插件包…"), false, "ext.pack_syncing");
      try {
        var syncData = await apiJson("POST", "/api/admin/plugin-packs/" + encodeURIComponent(syncId) + "/sync");
        await refreshAll(syncData.packs);
        setStatus(packStatusEl, t("ext.pack_synced", null, "插件包已同步至最新版本"), false, "ext.pack_synced");
      } catch (error) {
        setStatus(packStatusEl, error.message, true);
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
      var delPackId = packDelBtn.dataset.extPackDelete;
      packDelBtn.disabled = true;
      try {
        var packDelData = await apiJson("DELETE", "/api/admin/plugin-packs/" + encodeURIComponent(delPackId));
        if (activeExtId && activeExtId.indexOf(delPackId + ".") === 0) closeDrawer();
        if (activePackFilter === delPackId) activePackFilter = "";
        await refreshAll(packDelData.packs);
        setStatus(packStatusEl, t("ext.pack_deleted", null, "已退订并移除插件包"), false, "ext.pack_deleted");
      } catch (error) {
        setStatus(packStatusEl, error.message, true);
        packDelBtn.disabled = false;
      }
    }
  });

  if (drawerBackdropEl) {
    drawerBackdropEl.addEventListener("click", closeDrawer);
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawerEl && !drawerEl.hidden) {
      event.preventDefault();
      closeDrawer();
    }
  });

  panel.addEventListener("change", async function (event) {
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
      setStatus(panelStatusEl, "", false);
    } catch (error) {
      toggle.checked = !nextEnabled;
      toggle.disabled = false;
      setStatus(panelStatusEl, error.message, true);
    }
  });

  if (drawerFormEl) {
    drawerFormEl.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (!activeExtId || drawerSaving) return;
      drawerSaving = true;
      if (drawerSaveBtn) drawerSaveBtn.disabled = true;
      setStatus(drawerStatusEl, t("resume.saving", null, "保存中…"), false, "resume.saving");

      var config = {};
      Array.from(drawerFormEl.elements).forEach(function (field) {
        if (!field.name) return;
        var kind = field.dataset.fieldKind || field.type;
        if (kind === "boolean" || field.type === "checkbox") {
          config[field.name] = Boolean(field.checked);
        } else if (kind === "range" || kind === "number") {
          config[field.name] = field.value === "" ? null : Number(field.value);
        } else if (kind === "textarea" && field.dataset.fieldList === "1") {
          config[field.name] = field.value
            .split("\n")
            .map(function (line) { return line.trim(); })
            .filter(Boolean);
        } else if (kind === "secret") {
          var secretVal = field.value.trim();
          if (secretVal) {
            config[field.name] = secretVal;
          } else if (field.dataset.secretCleared === "1") {
            config["clear_" + field.name] = true;
          }
        } else {
          config[field.name] = field.value.trim();
        }
      });

      try {
        var res = await apiJson("PATCH", base + "/extensions/" + encodeURIComponent(activeExtId), {
          config: config
        });
        if (res.extension) {
          replaceExt(res.extension);
          updateSingleCard(res.extension);
          syncDrawerSecrets(res.extension);
        }
        setStatus(drawerStatusEl, t("blog.ext_saved", null, "配置已保存"), false, "blog.ext_saved");
      } catch (error) {
        setStatus(
          drawerStatusEl,
          t("resume.save_failed", null, "保存失败") + "：" + error.message,
          true
        );
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
    }
    refreshStatusLang(panelStatusEl);
    refreshStatusLang(packStatusEl);
    refreshStatusLang(drawerStatusEl);
  });

  renderPackFilters();
  renderPacksList();
  applyFilters();
})();
