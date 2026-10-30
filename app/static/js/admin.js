(function () {
  "use strict";

  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var CSRF = csrfMeta ? csrfMeta.getAttribute("content") : "";

  function t(key, vars, fallback) {
    if (window.SiteFlowI18n && window.SiteFlowI18n.t) {
      return window.SiteFlowI18n.t(key, vars);
    }
    return fallback || key;
  }

  function api(method, path, body) {
    var options = { method: method, headers: { "X-CSRF-Token": CSRF } };
    if (body !== undefined) {
      options.body = JSON.stringify(body);
      options.headers["Content-Type"] = "application/json";
    }
    return fetch("/api/admin" + path, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.ok === false) {
          var rawErr = data.error ? (window.SiteFlowI18n ? window.SiteFlowI18n.translateText(data.error) : data.error) : t("js.req_failed", null, "请求失败");
          throw new Error(rawErr);
        }
        return data;
      });
    });
  }

  function refresh() { location.reload(); }

  function onError(error) {
    var msg = (error && error.message) ? error.message : String(error);
    if (window.SiteFlowI18n && window.SiteFlowI18n.translateText) {
      msg = window.SiteFlowI18n.translateText(msg);
    }
    alert(msg);
  }

  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");

  var uploading = false;
  var failedFiles = [];

  document.querySelectorAll('[data-action="show-create"]').forEach(function (button) {
    button.addEventListener("click", function () {
      var panel = document.getElementById(button.dataset.panel);
      var open = panel.hidden;
      document.querySelectorAll(".create-panel").forEach(function (item) { item.hidden = true; });
      document.querySelectorAll('[data-action="show-create"]').forEach(function (item) {
        item.setAttribute("aria-expanded", "false");
      });
      panel.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      if (open && panel.id === "link-panel") panel.querySelector("input").focus();
    });
  });

  if (dropzone) {
    dropzone.addEventListener("click", function () { if (!uploading) fileInput.click(); });
    dropzone.addEventListener("dragover", function (event) {
      event.preventDefault();
      dropzone.classList.add("active");
    });
    dropzone.addEventListener("dragleave", function () { dropzone.classList.remove("active"); });
    dropzone.addEventListener("drop", function (event) {
      event.preventDefault();
      dropzone.classList.remove("active");
      uploadFiles(Array.from(event.dataTransfer.files));
    });
    fileInput.addEventListener("change", function () {
      uploadFiles(Array.from(fileInput.files));
      fileInput.value = "";
    });
    document.getElementById("retry-uploads").addEventListener("click", function () {
      uploadFiles(failedFiles.slice());
    });
  }

  function parentId() {
    var value = document.body.getAttribute("data-parent-id");
    return value ? parseInt(value, 10) : null;
  }

  function uploadFile(file, status) {
    return new Promise(function (resolve, reject) {
      var form = new FormData();
      form.append("file", file);
      var parent = parentId();
      if (parent) form.append("parent_id", String(parent));
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/admin/projects/upload");
      xhr.setRequestHeader("X-CSRF-Token", CSRF);
      xhr.timeout = 300000;
      xhr.upload.onprogress = function (event) {
        if (event.lengthComputable) status.textContent = Math.round(event.loaded / event.total * 100) + "%";
      };
      xhr.upload.onload = function () { status.textContent = t("admin.processing"); };
      xhr.onload = function () {
        try {
          var data = JSON.parse(xhr.responseText);
          if (xhr.status < 200 || xhr.status >= 300 || data.ok === false) {
            throw new Error(data.error ? (window.SiteFlowI18n ? window.SiteFlowI18n.translateText(data.error) : data.error) : t("js.upload_failed"));
          }
          resolve(data);
        } catch (error) { reject(error); }
      };
      xhr.onerror = xhr.ontimeout = function () { reject(new Error(t("js.network_error"))); };
      xhr.send(form);
    });
  }

  async function uploadFiles(files) {
    if (uploading || !files.length) return;
    uploading = true;
    failedFiles = [];
    dropzone.disabled = true;
    var results = document.getElementById("upload-results");
    var retry = document.getElementById("retry-uploads");
    results.textContent = "";
    retry.hidden = true;
    try {
      for (var file of files) {
        var item = document.createElement("div");
        item.className = "upload-result";
        var name = document.createElement("span");
        name.textContent = file.name;
        var status = document.createElement("span");
        status.textContent = t("admin.processing");
        item.append(name, status);
        results.append(item);
        try {
          var data = await uploadFile(file, status);
          status.textContent = "";
          var link = document.createElement("a");
          link.href = "/projects/" + data.project.slug + "/";
          link.target = "_blank";
          link.textContent = t("admin.upload_success");
          status.append(link);
        } catch (error) {
          failedFiles.push(file);
          status.textContent = t("js.upload_failed") + " · " + error.message;
          item.classList.add("is-error");
        }
      }
      var response = await fetch(location.href);
      if (!response.ok) throw new Error(t("js.req_failed"));
      var html = new DOMParser().parseFromString(await response.text(), "text/html");
      var list = html.getElementById("project-list");
      if (!list) throw new Error(t("js.req_failed"));
      document.getElementById("project-list").replaceWith(list);
      if (window.SiteFlowI18n) window.SiteFlowI18n.applyI18n();
    } catch (error) { onError(error); }
    finally {
      uploading = false;
      dropzone.disabled = false;
      retry.hidden = !failedFiles.length;
    }
  }

  window.addEventListener("beforeunload", function (event) {
    if (uploading) { event.preventDefault(); event.returnValue = ""; }
  });

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches('input[type="file"][name="cover"]')) return;
    var picker = input.closest(".file-picker");
    var label = picker ? picker.querySelector(".file-name") : null;
    if (label) label.textContent = input.files.length ? input.files[0].name : t("row.no_file", null, "未选择");
  });

  var linkUrl = document.getElementById("link-url");
  if (linkUrl) {
    document.getElementById("link-panel").addEventListener("submit", function (event) {
      event.preventDefault();
      var url = linkUrl.value.trim();
      if (!url) return;
      var button = this.querySelector("button");
      button.disabled = true;
      api("POST", "/projects/link", { url: url, parent_id: parentId() })
        .then(refresh)
        .catch(onError)
        .finally(function () { button.disabled = false; });
    });
  }

  // Space Theme customization
  var saveThemeBtn = document.getElementById("save-theme-btn");
  if (saveThemeBtn) {
    var swatches = document.querySelectorAll(".swatch[data-color]");
    var accentPicker = document.getElementById("theme-accent-picker");
    var accentText = document.getElementById("theme-accent");
    var fontSelect = document.getElementById("theme-font");
    var radiusSelect = document.getElementById("theme-radius");
    var tip = document.getElementById("theme-save-tip");

    swatches.forEach(function (sw) {
      sw.addEventListener("click", function () {
        var c = sw.getAttribute("data-color");
        if (accentText) accentText.value = c;
        if (accentPicker) accentPicker.value = c;
      });
    });

    if (accentPicker && accentText) {
      accentPicker.addEventListener("input", function () {
        accentText.value = accentPicker.value;
      });
      accentText.addEventListener("input", function () {
        if (/^#[0-9a-fA-F]{6}$/.test(accentText.value)) {
          accentPicker.value = accentText.value;
        }
      });
    }

    saveThemeBtn.addEventListener("click", function () {
      var pid = parentId();
      if (!pid) return;
      var theme = {
        accent: accentText ? accentText.value.trim() : "",
        font_family: fontSelect ? fontSelect.value : "",
        radius_card: radiusSelect ? radiusSelect.value : ""
      };
      api("PATCH", "/projects/" + pid, { theme: theme })
        .then(function () {
          if (tip) {
            tip.textContent = t("js.theme_saved", null, "✓ 空间主题已保存生效");
            tip.style.color = "var(--accent)";
            setTimeout(function () { tip.textContent = ""; }, 3000);
          }
        })
        .catch(onError);
    });
  }

  document.addEventListener("click", function (event) {
    var fileButton = event.target.closest(".file-button");
    if (fileButton) {
      var fileInput = fileButton.closest(".file-picker").querySelector('input[type="file"]');
      if (fileInput) fileInput.click();
      return;
    }
    var button = event.target.closest("[data-action]");
    if (!button) return;
    var action = button.getAttribute("data-action");
    var row = button.closest(".row");
    var id = row ? row.getAttribute("data-id") : null;

    if (action === "create-app") {
      var appType = button.getAttribute("data-type");
      api("POST", "/projects/app", {
        type: appType,
        title: appType === "space" ? t("js.new_space_default", null, "新空间") : "",
        parent_id: parentId()
      }).then(function (data) {
        if (data.project && data.project.id) {
          location.href = "/admin/projects/" + data.project.id;
          return;
        }
        refresh();
      }).catch(onError);
      return;
    }
    if (action === "logout") {
      fetch("/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF },
        redirect: "follow"
      })
        .then(refresh)
        .catch(onError);
      return;
    }
    if (action === "copy-api-token") {
      var tokenVal = button.getAttribute("data-token") || "";
      var labelSpan = button.querySelector("span");
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(tokenVal).then(function () {
          if (labelSpan) labelSpan.textContent = t("js.api_copied", null, "已复制密钥");
          setTimeout(function () {
            if (labelSpan) labelSpan.textContent = t("admin.copy_api_key", null, "复制 API 密钥");
          }, 1800);
        }).catch(onError);
      }
      return;
    }
    if (!row) return;


    if (action === "edit") {
      var editor = row.querySelector(".editor");
      editor.hidden = !editor.hidden;
    } else if (action === "remove-cover") {
      api("DELETE", "/projects/" + id + "/cover").then(refresh).catch(onError);
    } else if (action === "clear-password") {
      if (confirm(t("js.confirm_clear_pwd", null, "确定清除此作品的访问密码？清除后任何人均可公开直接访问。"))) {
        api("PATCH", "/projects/" + id, { password: "" }).then(refresh).catch(onError);
      }
    } else if (action === "save") {
      var titleInput = row.querySelector('[name="title"]');
      var descInput = row.querySelector('[name="description"]');
      function canonicalVal(inp) {
        if (!inp) return "";
        var v = inp.value;
        if (inp.dataset && inp.dataset.enVal && inp.dataset.zhVal && v.trim() === inp.dataset.enVal.trim() && !inp.dataset.userEdited) {
          return inp.dataset.zhVal;
        }
        return v;
      }
      var payload = {
        title: canonicalVal(titleInput),
        description: canonicalVal(descInput)
      };
      var urlInput = row.querySelector('[name="url"]');
      if (urlInput) payload.url = urlInput.value;
      var pwdInput = row.querySelector('[name="password"]');
      if (pwdInput && pwdInput.value.trim() !== "") {
        payload.password = pwdInput.value.trim();
      }
      button.disabled = true;
      api("PATCH", "/projects/" + id, payload)
        .then(function () {
          var coverInput = row.querySelector('[name="cover"]');
          if (!coverInput.files.length) return;
          var coverForm = new FormData();
          coverForm.append("file", coverInput.files[0]);
          return fetch("/api/admin/projects/" + id + "/cover", {
            method: "POST",
            headers: { "X-CSRF-Token": CSRF },
            body: coverForm
          }).then(function (response) {
            if (!response.ok) throw new Error(t("js.cover_failed", null, "封面上传失败"));
          });
        })
        .then(refresh)
        .catch(onError)
        .finally(function () { button.disabled = false; });
    } else if (action === "toggle-pin") {
      var pinned = button.getAttribute("data-pinned") === "true";
      api("PATCH", "/projects/" + id, { pinned: !pinned }).then(refresh).catch(onError);
    } else if (action === "toggle-visible") {
      var visible = button.getAttribute("data-visible") === "true";
      api("PATCH", "/projects/" + id, { visible: !visible }).then(refresh).catch(onError);
    } else if (action === "move-up") {
      api("POST", "/projects/" + id + "/move", { direction: "up" }).then(refresh).catch(onError);
    } else if (action === "move-down") {
      api("POST", "/projects/" + id + "/move", { direction: "down" }).then(refresh).catch(onError);
    } else if (action === "delete") {
      if (confirm(t("js.confirm_delete", null, "确定删除该作品？文件将一并删除，不可恢复。"))) {
        api("DELETE", "/projects/" + id).then(refresh).catch(onError);
      }
    }
  });
})();
