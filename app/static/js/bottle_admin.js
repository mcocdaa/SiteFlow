(function () {
  "use strict";

  var projectId = document.body.getAttribute("data-plugin-id");
  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var CSRF = csrfMeta ? csrfMeta.getAttribute("content") : "";
  if (!projectId) return;

  var subListEl = document.getElementById("submission-list");
  var banListEl = document.getElementById("banned-list");
  var subPanelEl = document.getElementById("submission-panel");
  var banPanelEl = document.getElementById("banned-panel");
  var modStatusEl = document.getElementById("mod-status");
  var refreshBtn = document.getElementById("refresh-submissions-btn");
  var clearBtn = document.getElementById("clear-submissions-btn");
  var clearDialog = document.getElementById("clear-confirm-dialog");
  var clearCurrentBtn = document.getElementById("clear-current-btn");

  var settingsForm = document.getElementById("bottle-settings-form");
  var saveStateEl = document.getElementById("settings-save-state");
  var saveSettingsBtn = document.getElementById("save-bottle-settings");

  var activeTab = "pending";
  var lastItems = [];
  var lastBanned = [];

  function t(key, vars, fallback) {
    if (window.SiteFlowI18n && window.SiteFlowI18n.t) {
      return window.SiteFlowI18n.t(key, vars);
    }
    return fallback || key;
  }

  function translateText(text) {
    if (!text) return "";
    if (window.SiteFlowI18n && window.SiteFlowI18n.translateText) {
      return window.SiteFlowI18n.translateText(text);
    }
    return text;
  }

  function adminApi(method, path, body) {
    var options = { method: method, headers: { "X-CSRF-Token": CSRF } };
    if (body !== undefined) {
      options.body = JSON.stringify(body);
      options.headers["Content-Type"] = "application/json";
    }
    return fetch("/api/admin/projects/" + projectId + path, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || data.ok === false) {
          throw new Error(data.error ? translateText(data.error) : t("js.req_failed", null, "请求失败"));
        }
        return data;
      });
    });
  }

  function setModStatus(kind, message) {
    if (!modStatusEl) return;
    modStatusEl.classList.remove("is-success", "is-error");
    if (!message) {
      modStatusEl.hidden = true;
      modStatusEl.textContent = "";
      return;
    }
    modStatusEl.hidden = false;
    modStatusEl.textContent = message;
    if (kind === "success") modStatusEl.classList.add("is-success");
    if (kind === "error") modStatusEl.classList.add("is-error");
  }

  function updateCounts(counts, bannedCount) {
    var map = {
      "count-pending": counts && typeof counts.pending === "number" ? counts.pending : 0,
      "count-approved": counts && typeof counts.approved === "number" ? counts.approved : 0,
      "count-rejected": counts && typeof counts.rejected === "number" ? counts.rejected : 0,
      "count-banned": typeof bannedCount === "number" ? bannedCount : lastBanned.length
    };
    Object.keys(map).forEach(function (id) {
      var node = document.getElementById(id);
      if (node) node.textContent = String(map[id]);
    });
  }

  function formatTime(iso) {
    if (!iso) return "";
    return String(iso).replace("T", " ").slice(0, 19);
  }

  function makeEl(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function statusLabel(status) {
    if (status === "approved") return t("bottle.tab_approved", null, "已通过");
    if (status === "rejected") return t("bottle.tab_rejected", null, "已拒绝");
    return t("bottle.tab_pending", null, "待审核");
  }

  function renderSubmissions(items) {
    if (!subListEl) return;
    lastItems = items || [];
    subListEl.textContent = "";
    if (!lastItems.length) {
      subListEl.append(makeEl("div", "bottle-empty-queue", t("bottle.admin_empty_queue", null, "当前分类暂无漂流瓶记录。")));
      return;
    }
    var bannedSet = {};
    lastBanned.forEach(function (entry) { bannedSet[entry.ip_hash] = true; });

    lastItems.forEach(function (item) {
      var payload = item.payload && typeof item.payload === "object" ? item.payload : {};
      var card = makeEl("article", "bottle-sub-item");
      card.setAttribute("data-sub-id", String(item.id));

      var msg = makeEl("p", "bottle-sub-msg", String(payload.message || ""));
      card.append(msg);

      var meta = makeEl("div", "bottle-sub-meta");
      meta.append(makeEl("span", "bottle-status-tag status-" + item.status, statusLabel(item.status)));
      var nick = String(payload.nickname || "").trim() || t("bottle.anonymous_author", null, "匿名旅人");
      meta.append(makeEl("span", "", nick));
      meta.append(makeEl("span", "", formatTime(item.created_at)));
      meta.append(makeEl("code", "", "IP #" + String(item.ip_hash || "").slice(0, 10)));
      card.append(meta);

      var actions = makeEl("div", "bottle-sub-actions");
      if (item.status !== "approved") {
        var approveBtn = makeEl("button", "btn btn-sm primary", t("bottle.action_approve", null, "通过"));
        approveBtn.type = "button";
        approveBtn.setAttribute("data-sub-action", "approve");
        approveBtn.setAttribute("data-sub-id", String(item.id));
        actions.append(approveBtn);
      }
      if (item.status !== "rejected") {
        var rejectBtn = makeEl("button", "btn btn-sm", t("bottle.action_reject", null, "拒绝"));
        rejectBtn.type = "button";
        rejectBtn.setAttribute("data-sub-action", "reject");
        rejectBtn.setAttribute("data-sub-id", String(item.id));
        actions.append(rejectBtn);
      }
      if (!bannedSet[item.ip_hash]) {
        var banBtn = makeEl("button", "btn btn-sm ghost", t("bottle.action_ban_ip", null, "封禁该 IP"));
        banBtn.type = "button";
        banBtn.setAttribute("data-ban-ip", String(item.ip_hash));
        actions.append(banBtn);
      }
      var delBtn = makeEl("button", "btn btn-sm danger", t("row.delete", null, "删除"));
      delBtn.type = "button";
      delBtn.setAttribute("data-sub-action", "delete");
      delBtn.setAttribute("data-sub-id", String(item.id));
      actions.append(delBtn);

      card.append(actions);
      subListEl.append(card);
    });
  }

  function renderBanned(banned) {
    if (!banListEl) return;
    lastBanned = banned || [];
    banListEl.textContent = "";
    if (!lastBanned.length) {
      banListEl.append(makeEl("div", "bottle-empty-queue", t("bottle.admin_empty_bans", null, "暂无已封禁 IP。")));
      return;
    }
    lastBanned.forEach(function (entry) {
      var row = makeEl("div", "bottle-ban-item");
      var info = makeEl("div", "bottle-sub-meta");
      info.append(makeEl("code", "", entry.ip_hash));
      info.append(makeEl("span", "", formatTime(entry.created_at)));
      var unbanBtn = makeEl("button", "btn btn-sm", t("bottle.action_unban_ip", null, "解除封禁"));
      unbanBtn.type = "button";
      unbanBtn.setAttribute("data-unban-ip", entry.ip_hash);
      row.append(info, unbanBtn);
      banListEl.append(row);
    });
  }

  function loadQueue() {
    var queryStatus = activeTab === "banned" ? "pending" : activeTab;
    return adminApi("GET", "/submissions?plugin_id=bottle&status=" + encodeURIComponent(queryStatus))
      .then(function (data) {
        renderBanned(data.banned_ips || []);
        updateCounts(data.counts || {}, (data.banned_ips || []).length);
        if (activeTab !== "banned") {
          renderSubmissions(data.submissions || []);
        }
      })
      .catch(function (error) {
        setModStatus("error", error.message || t("js.req_failed", null, "请求失败"));
      });
  }

  function switchTab(nextTab) {
    activeTab = nextTab;
    document.querySelectorAll(".bottle-tab").forEach(function (tab) {
      var isCurrent = tab.getAttribute("data-tab") === nextTab;
      tab.classList.toggle("is-active", isCurrent);
      tab.setAttribute("aria-selected", isCurrent ? "true" : "false");
    });
    if (subPanelEl && banPanelEl) {
      subPanelEl.hidden = nextTab === "banned";
      banPanelEl.hidden = nextTab !== "banned";
      if (nextTab !== "banned") {
        subPanelEl.setAttribute("aria-labelledby", "tab-" + nextTab);
      }
    }
    if (clearCurrentBtn) {
      clearCurrentBtn.hidden = nextTab === "banned";
    }
    loadQueue();
  }

  document.querySelectorAll(".bottle-tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      switchTab(tab.getAttribute("data-tab") || "pending");
    });
  });

  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      setModStatus("", "");
      loadQueue();
    });
  }

  if (clearBtn && clearDialog) {
    clearBtn.addEventListener("click", function () {
      if (clearCurrentBtn) {
        clearCurrentBtn.hidden = activeTab === "banned";
      }
      clearDialog.showModal();
    });
    clearDialog.addEventListener("close", function () {
      var choice = clearDialog.returnValue;
      clearDialog.returnValue = "";
      if (choice !== "current" && choice !== "all") return;
      var payload = { plugin_id: "bottle" };
      if (choice === "current" && activeTab !== "banned") {
        payload.status = activeTab;
      }
      adminApi("POST", "/submissions/clear", payload)
        .then(function (data) {
          setModStatus(
            "success",
            t("bottle.admin_cleared", { n: data.deleted || 0 }, "已清空 " + (data.deleted || 0) + " 条漂流瓶记录")
          );
          return loadQueue();
        })
        .catch(function (error) {
          setModStatus("error", error.message || t("js.req_failed", null, "请求失败"));
        });
    });
  }

  document.addEventListener("click", function (event) {
    var actionBtn = event.target.closest("[data-sub-action]");
    if (actionBtn) {
      var subId = actionBtn.getAttribute("data-sub-id");
      var action = actionBtn.getAttribute("data-sub-action");
      actionBtn.disabled = true;
      adminApi("POST", "/submissions/" + encodeURIComponent(subId) + "/status", { action: action })
        .then(function () {
          setModStatus("success", t("bottle.admin_action_done", null, "操作已完成"));
          return loadQueue();
        })
        .catch(function (error) {
          setModStatus("error", error.message || t("js.req_failed", null, "请求失败"));
        })
        .finally(function () {
          actionBtn.disabled = false;
        });
      return;
    }

    var banBtn = event.target.closest("[data-ban-ip]");
    if (banBtn) {
      var ipHash = banBtn.getAttribute("data-ban-ip");
      banBtn.disabled = true;
      adminApi("POST", "/submissions/ban", { ip_hash: ipHash })
        .then(function () {
          setModStatus("success", t("bottle.admin_ip_banned", null, "已封禁该 IP"));
          return loadQueue();
        })
        .catch(function (error) {
          setModStatus("error", error.message || t("js.req_failed", null, "请求失败"));
        })
        .finally(function () {
          banBtn.disabled = false;
        });
      return;
    }

    var unbanBtn = event.target.closest("[data-unban-ip]");
    if (unbanBtn) {
      var targetHash = unbanBtn.getAttribute("data-unban-ip");
      unbanBtn.disabled = true;
      adminApi("DELETE", "/submissions/ban/" + encodeURIComponent(targetHash))
        .then(function () {
          setModStatus("success", t("bottle.admin_ip_unbanned", null, "已解除该 IP 封禁"));
          return loadQueue();
        })
        .catch(function (error) {
          setModStatus("error", error.message || t("js.req_failed", null, "请求失败"));
        })
        .finally(function () {
          unbanBtn.disabled = false;
        });
    }
  });

  if (settingsForm) {
    settingsForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!settingsForm.reportValidity()) return;
      if (saveSettingsBtn) saveSettingsBtn.disabled = true;
      if (saveStateEl) {
        saveStateEl.classList.remove("is-error");
        saveStateEl.textContent = t("resume.saving", null, "保存中…");
      }
      var payload = {
        intro: document.getElementById("f-intro").value.trim(),
        placeholder: document.getElementById("f-placeholder").value.trim(),
        max_length: parseInt(document.getElementById("f-max-length").value, 10),
        throw_limit_per_hour: parseInt(document.getElementById("f-throw-limit").value, 10),
        pick_limit_per_hour: parseInt(document.getElementById("f-pick-limit").value, 10),
        require_approval: document.getElementById("f-require-approval").checked,
        throw_to_pick: document.getElementById("f-throw-to-pick").checked,
        allow_links: document.getElementById("f-allow-links").checked
      };
      adminApi("PATCH", "", { content: JSON.stringify(payload) })
        .then(function () {
          if (saveStateEl) {
            saveStateEl.classList.remove("is-error");
            saveStateEl.textContent = t("bottle.settings_saved", null, "规则配置已保存");
          }
        })
        .catch(function (error) {
          if (saveStateEl) {
            saveStateEl.classList.add("is-error");
            saveStateEl.textContent = error.message || t("resume.save_failed", null, "保存失败");
          }
        })
        .finally(function () {
          if (saveSettingsBtn) saveSettingsBtn.disabled = false;
        });
    });
  }

  window.addEventListener("siteflow:langchange", function () {
    renderSubmissions(lastItems);
    renderBanned(lastBanned);
  });

  loadQueue();
})();
