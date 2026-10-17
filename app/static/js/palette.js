(function () {
  "use strict";

  var overlay = document.getElementById("cmd-palette");
  if (!overlay) return;

  var input = document.getElementById("palette-input");
  var resultsBox = document.getElementById("palette-results");
  var closeBtn = document.getElementById("palette-close");

  var activeIndex = 0;
  var items = [];
  var debounceTimer = null;

  function t(key, fallback) {
    if (window.SiteFlowI18n && window.SiteFlowI18n.t) {
      return window.SiteFlowI18n.t(key);
    }
    return fallback || key;
  }

  function translateText(str) {
    if (window.SiteFlowI18n && window.SiteFlowI18n.translateText) {
      return window.SiteFlowI18n.translateText(str);
    }
    return str;
  }

  function getSystemCommands() {
    return [
      {
        id: "cmd-theme",
        title: t("palette.cmd_theme_title", "切换外观模式 (浅色 / 暗色)"),
        description: t("palette.cmd_theme_desc", "在暗夜黑与清爽白外观之间无缝切换"),
        type: "action",
        action: function () {
          var isDark = document.documentElement.getAttribute("data-theme") === "dark" ||
            (!document.documentElement.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
          var nextTheme = isDark ? "light" : "dark";
          document.documentElement.setAttribute("data-theme", nextTheme);
          try {
            localStorage.setItem("sf_theme", nextTheme);
          } catch (e) {}
        }
      },
      {
        id: "cmd-lang",
        title: t("palette.cmd_lang_title", "切换界面语言 (中文 / EN)"),
        description: t("palette.cmd_lang_desc", "在中文与英文界面之间即时切换"),
        type: "action",
        action: function () {
          if (window.SiteFlowI18n && window.SiteFlowI18n.toggleLang) {
            window.SiteFlowI18n.toggleLang();
          }
        }
      },
      {
        id: "cmd-gallery",
        title: t("palette.cmd_gallery_title", "返回画廊首页"),
        description: t("palette.cmd_gallery_desc", "浏览聚合展示的所有静态作品与空间"),
        type: "nav",
        url: "/"
      },
      {
        id: "cmd-admin",
        title: t("palette.cmd_admin_title", "进入管理控制台"),
        description: t("palette.cmd_admin_desc", "上传作品、配置空间主题与查看访问统计"),
        type: "nav",
        url: "/admin"
      }
    ];
  }

  // Restore saved theme on load
  try {
    var savedTheme = localStorage.getItem("sf_theme");
    if (savedTheme) {
      document.documentElement.setAttribute("data-theme", savedTheme);
    }
  } catch (e) {}

  function openPalette() {
    overlay.hidden = false;
    overlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    input.value = "";
    activeIndex = 0;
    fetchResults("");
    setTimeout(function () {
      input.focus();
    }, 50);
  }

  function closePalette() {
    overlay.hidden = true;
    overlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    input.value = "";
  }

  function renderList() {
    resultsBox.innerHTML = "";
    if (items.length === 0) {
      resultsBox.innerHTML = '<div class="palette-empty">' + escapeHtml(t("palette.empty", "无匹配结果，尝试更换搜索关键词")) + '</div>';
      return;
    }

    var currentGroup = "";
    items.forEach(function (item, idx) {
      var groupName = item.group || (item.type === "action" || item.type === "nav" ? t("palette.group_actions", "快捷操作") : t("palette.group_projects", "空间与作品"));
      if (groupName !== currentGroup) {
        currentGroup = groupName;
        var groupEl = document.createElement("div");
        groupEl.className = "palette-group-title";
        groupEl.textContent = currentGroup;
        resultsBox.appendChild(groupEl);
      }

      var el = document.createElement("div");
      el.className = "palette-item" + (idx === activeIndex ? " active" : "");
      el.setAttribute("role", "option");
      el.setAttribute("data-index", idx);

      var typeBadge = item.type.toUpperCase();
      var dispTitle = translateText(item.title);
      var dispSpace = item.space ? translateText(item.space) : "";
      var dispDesc = item.description ? translateText(item.description) : "";

      var metaHtml = "";
      if (dispSpace) {
        metaHtml += '<span class="palette-space-tag">' + escapeHtml(dispSpace) + '</span>';
      }
      if (dispDesc) {
        metaHtml += '<span class="palette-item-desc">' + escapeHtml(dispDesc) + '</span>';
      }

      el.innerHTML =
        '<div class="palette-item-main">' +
          '<div class="palette-item-title">' +
            '<span>' + escapeHtml(dispTitle) + '</span>' +
            '<span class="palette-badge palette-badge-' + item.type + '">' + typeBadge + '</span>' +
          '</div>' +
          (metaHtml ? '<div class="palette-item-meta">' + metaHtml + '</div>' : '') +
        '</div>' +
        '<span class="palette-item-enter">↵</span>';

      el.addEventListener("click", function () {
        selectItem(idx);
      });

      resultsBox.appendChild(el);
    });

    scrollActiveIntoView();
  }

  function scrollActiveIntoView() {
    var activeEl = resultsBox.querySelector(".palette-item.active");
    if (activeEl) {
      activeEl.scrollIntoView({ block: "nearest" });
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
    });
  }

  function fetchResults(query) {
    var q = query.trim().toLowerCase();
    var sysCmds = getSystemCommands();
    var filteredCmds = sysCmds.filter(function (cmd) {
      return !q || cmd.title.toLowerCase().indexOf(q) !== -1 || cmd.description.toLowerCase().indexOf(q) !== -1;
    });

    fetch("/api/search?q=" + encodeURIComponent(q))
      .then(function (res) {
        if (!res.ok) return [];
        return res.json();
      })
      .then(function (projects) {
        items = filteredCmds.concat(projects);
        activeIndex = 0;
        renderList();
      })
      .catch(function () {
        items = filteredCmds;
        activeIndex = 0;
        renderList();
      });
  }

  function selectItem(idx) {
    var item = items[idx];
    if (!item) return;
    closePalette();

    if (item.action) {
      item.action();
    } else if (item.url) {
      location.href = item.url;
    }
  }

  window.addEventListener("siteflow:langchange", function () {
    if (!overlay.hidden) {
      fetchResults(input.value);
    }
  });

  // Keyboard navigation inside palette
  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (items.length > 0) {
        activeIndex = (activeIndex + 1) % items.length;
        renderList();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (items.length > 0) {
        activeIndex = (activeIndex - 1 + items.length) % items.length;
        renderList();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      selectItem(activeIndex);
    } else if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
    }
  });

  input.addEventListener("input", function () {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      fetchResults(input.value);
    }, 120);
  });

  // Global hotkeys
  document.addEventListener("keydown", function (e) {
    // Cmd+K / Ctrl+K
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (overlay.hidden) {
        openPalette();
      } else {
        closePalette();
      }
      return;
    }

    // Slash shortcut when not typing
    if (e.key === "/" && overlay.hidden) {
      var tag = (document.activeElement && document.activeElement.tagName) || "";
      if (tag !== "INPUT" && tag !== "TEXTAREA" && !document.activeElement.isContentEditable) {
        e.preventDefault();
        openPalette();
      }
      return;
    }

    if (e.key === "Escape" && !overlay.hidden) {
      closePalette();
    }
  });

  // Open triggers
  document.addEventListener("click", function (e) {
    if (e.target.closest('[data-action="open-palette"], #cmd-k-trigger')) {
      e.preventDefault();
      openPalette();
    }
  });

  if (closeBtn) closeBtn.addEventListener("click", closePalette);
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closePalette();
  });

  window.SiteFlowPalette = { open: openPalette, close: closePalette };
})();
