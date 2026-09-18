(function () {
  "use strict";

  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var CSRF = csrfMeta ? csrfMeta.getAttribute("content") : "";
  var dataNode = document.getElementById("resume-data");
  var body = document.body;
  var projectId = body.getAttribute("data-resume-id");
  var state = dataNode ? JSON.parse(dataNode.textContent) : {};

  var ICONS = {
    up: '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>',
    down: '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>',
    trash: '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>'
  };

  var SECTION_FIELDS = {
    work: [
      ["name", "公司", "text"],
      ["position", "职位", "text"],
      ["startDate", "开始", "text"],
      ["endDate", "结束", "text"],
      ["url", "链接", "text"],
      ["summary", "摘要", "textarea"],
      ["highlights", "要点（每行一条）", "list"]
    ],
    education: [
      ["institution", "学校", "text"],
      ["area", "专业", "text"],
      ["studyType", "学历", "text"],
      ["startDate", "开始", "text"],
      ["endDate", "结束", "text"]
    ],
    projects: [
      ["name", "名称", "text"],
      ["url", "链接", "text"],
      ["description", "描述", "textarea"],
      ["highlights", "要点（每行一条）", "list"],
      ["keywords", "关键词（逗号分隔）", "tags"]
    ],
    skills: [
      ["name", "技能", "text"],
      ["keywords", "关键词（逗号分隔）", "tags"]
    ]
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fieldValue(entry, field, kind) {
    var value = entry[field];
    if (kind === "list") return Array.isArray(value) ? value.join("\n") : "";
    if (kind === "tags") return Array.isArray(value) ? value.join(", ") : "";
    return typeof value === "string" ? value : "";
  }

  function readValue(input, kind) {
    var text = input.value.trim();
    if (kind === "list") {
      return text ? text.split("\n").map(function (line) { return line.trim(); }).filter(Boolean) : [];
    }
    if (kind === "tags") {
      return text ? text.split(",").map(function (part) { return part.trim(); }).filter(Boolean) : [];
    }
    return text;
  }

  function renderEntry(section, entry, index) {
    var card = el("div", "entry-card");
    card.setAttribute("data-index", String(index));
    var head = el("div", "entry-head");
    head.append(el("span", "entry-order", "第 " + (index + 1) + " 条"));
    var actions = el("div", "entry-actions");
    [["entry-up", ICONS.up, "上移"], ["entry-down", ICONS.down, "下移"], ["entry-remove", ICONS.trash, "删除"]].forEach(function (item) {
      var button = el("button", "btn ghost icon-btn");
      button.type = "button";
      button.setAttribute("data-entry-action", item[0]);
      button.setAttribute("aria-label", item[2]);
      button.setAttribute("data-tip", item[2]);
      button.innerHTML = item[1];
      actions.append(button);
    });
    head.append(actions);
    card.append(head);
    var grid = el("div", "entry-grid");
    SECTION_FIELDS[section].forEach(function (field) {
      var label = el("label");
      label.append(el("span", undefined, field[1]));
      var input;
      if (field[2] === "textarea") {
        input = el("textarea");
        input.rows = 3;
      } else if (field[2] === "list") {
        input = el("textarea");
        input.rows = 3;
      } else {
        input = el("input");
        input.type = "text";
        input.autocomplete = "off";
      }
      input.value = fieldValue(entry, field[0], field[2]);
      input.setAttribute("data-field", field[0]);
      input.setAttribute("data-kind", field[2]);
      label.append(input);
      grid.append(label);
    });
    card.append(grid);
    return card;
  }

  function renderSection(section) {
    var container = document.querySelector('[data-section="' + section + '"] .entry-list');
    if (!container) return;
    container.textContent = "";
    (state[section] || []).forEach(function (entry, index) {
      container.append(renderEntry(section, entry, index));
    });
  }

  function loadBasics() {
    var basics = state.basics || {};
    var location = basics.location || {};
    document.getElementById("f-name").value = basics.name || "";
    document.getElementById("f-label").value = basics.label || "";
    document.getElementById("f-email").value = basics.email || "";
    document.getElementById("f-phone").value = basics.phone || "";
    document.getElementById("f-url").value = basics.url || "";
    document.getElementById("f-city").value = location.city || "";
    document.getElementById("f-region").value = location.region || "";
    document.getElementById("f-countryCode").value = location.countryCode || "";
    document.getElementById("f-summary").value = basics.summary || "";
    document.getElementById("f-links").value = (basics.profiles || [])
      .map(function (profile) { return (profile.network || profile.username || "") + "|" + (profile.url || ""); })
      .join("\n");
  }

  function collectBasics() {
    var profiles = document.getElementById("f-links").value.split("\n").map(function (line) {
      var parts = line.split("|");
      if (parts.length < 2) return null;
      return { network: parts[0].trim(), username: "", url: parts.slice(1).join("|").trim() };
    }).filter(function (profile) { return profile && profile.url; });
    return {
      name: document.getElementById("f-name").value.trim(),
      label: document.getElementById("f-label").value.trim(),
      email: document.getElementById("f-email").value.trim(),
      phone: document.getElementById("f-phone").value.trim(),
      url: document.getElementById("f-url").value.trim(),
      summary: document.getElementById("f-summary").value.trim(),
      location: {
        city: document.getElementById("f-city").value.trim(),
        region: document.getElementById("f-region").value.trim(),
        countryCode: document.getElementById("f-countryCode").value.trim()
      },
      profiles: profiles
    };
  }

  function collectSection(section) {
    var cards = document.querySelectorAll('[data-section="' + section + '"] .entry-card');
    var rows = [];
    cards.forEach(function (card) {
      var entry = {};
      card.querySelectorAll("[data-field]").forEach(function (input) {
        entry[input.getAttribute("data-field")] = readValue(input, input.getAttribute("data-kind"));
      });
      rows.push(entry);
    });
    return rows;
  }

  function collect() {
    var content = { basics: collectBasics(), work: [], education: [], projects: [], skills: [] };
    Object.keys(SECTION_FIELDS).forEach(function (section) {
      content[section] = collectSection(section);
    });
    return content;
  }

  function moveEntry(card, direction) {
    var sibling = direction === "up" ? card.previousElementSibling : card.nextElementSibling;
    if (!sibling) return;
    if (direction === "up") {
      card.parentNode.insertBefore(card, sibling);
    } else {
      card.parentNode.insertBefore(sibling, card);
    }
  }

  function save() {
    var status = document.getElementById("save-state");
    status.textContent = "保存中…";
    fetch("/api/admin/projects/" + projectId, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF },
      body: JSON.stringify({ content: JSON.stringify(collect()) })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.ok === false) throw new Error(data.error || "保存失败");
        state = collect();
        Object.keys(SECTION_FIELDS).forEach(renderSection);
        status.textContent = "已保存 " + new Date().toLocaleTimeString();
      });
    }).catch(function (error) {
      status.textContent = "";
      alert(error.message || String(error));
    });
  }

  loadBasics();
  Object.keys(SECTION_FIELDS).forEach(renderSection);

  document.addEventListener("click", function (event) {
    var addButton = event.target.closest("[data-add-entry]");
    if (addButton) {
      var section = addButton.closest("[data-section]").getAttribute("data-section");
      state[section] = collectSection(section);
      state[section].push({});
      renderSection(section);
      return;
    }
    var entryButton = event.target.closest("[data-entry-action]");
    if (entryButton) {
      var card = entryButton.closest(".entry-card");
      var sectionName = entryButton.closest("[data-section]").getAttribute("data-section");
      var action = entryButton.getAttribute("data-entry-action");
      if (action === "entry-remove") {
        card.remove();
      } else {
        moveEntry(card, action === "entry-up" ? "up" : "down");
      }
      state[sectionName] = collectSection(sectionName);
      renderSection(sectionName);
      return;
    }
    if (event.target.closest('[data-action="save-resume"]')) {
      save();
    }
  });
})();
