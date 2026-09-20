(function () {
  "use strict";

  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var CSRF = csrfMeta ? csrfMeta.getAttribute("content") : "";

  function api(method, path, body) {
    var options = { method: method, headers: { "X-CSRF-Token": CSRF } };
    if (body !== undefined) {
      options.body = JSON.stringify(body);
      options.headers["Content-Type"] = "application/json";
    }
    return fetch("/api/admin" + path, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || "请求失败");
        }
        return data;
      });
    });
  }

  function refresh() { location.reload(); }

  function onError(error) { alert(error.message || String(error)); }

  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");

  if (dropzone) {
    dropzone.addEventListener("click", function () { fileInput.click(); });
    dropzone.addEventListener("dragover", function (event) {
      event.preventDefault();
      dropzone.classList.add("active");
    });
    dropzone.addEventListener("dragleave", function () { dropzone.classList.remove("active"); });
    dropzone.addEventListener("drop", function (event) {
      event.preventDefault();
      dropzone.classList.remove("active");
      if (event.dataTransfer.files.length) uploadFile(event.dataTransfer.files[0]);
    });
    fileInput.addEventListener("change", function () {
      if (!fileInput.files.length) return;
      uploadFile(fileInput.files[0]);
      fileInput.value = "";
    });
  }

  function parentId() {
    var value = document.body.getAttribute("data-parent-id");
    return value ? parseInt(value, 10) : null;
  }

  function uploadFile(file) {
    var form = new FormData();
    form.append("file", file);
    var parent = parentId();
    if (parent) form.append("parent_id", String(parent));

    var dropzoneIdle = document.getElementById("dropzone-idle");
    var dropzoneStages = document.getElementById("dropzone-stages");
    var progressBar = document.getElementById("stage-progress-bar");
    var statusMsg = document.getElementById("stage-status-msg");
    var stageSteps = dropzoneStages ? dropzoneStages.querySelectorAll(".stage-step") : [];

    function setStage(stepNum, percent, message) {
      if (!dropzoneStages) return;
      dropzoneStages.hidden = false;
      if (dropzoneIdle) dropzoneIdle.hidden = true;
      if (dropzone) dropzone.classList.add("uploading");
      stageSteps.forEach(function (el) {
        var num = parseInt(el.getAttribute("data-step"), 10);
        el.classList.toggle("active", num === stepNum);
        el.classList.toggle("done", num < stepNum);
      });
      if (progressBar) progressBar.style.width = percent + "%";
      if (statusMsg) statusMsg.textContent = message;
    }

    function resetDropzone() {
      if (dropzoneStages) dropzoneStages.hidden = true;
      if (dropzoneIdle) dropzoneIdle.hidden = false;
      if (dropzone) dropzone.classList.remove("uploading");
    }

    setStage(1, 10, "正在准备上传制品...");

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/admin/projects/upload");
    xhr.setRequestHeader("X-CSRF-Token", CSRF);

    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        var percent = Math.round((e.loaded / e.total) * 45);
        setStage(1, Math.max(10, percent), "正在上传制品 (" + Math.round((e.loaded / e.total) * 100) + "%)...");
      }
    };

    xhr.upload.onload = function () {
      setStage(2, 65, "执行安全沙箱审计（ZipBomb 防御与容错转码）...");
      setTimeout(function () {
        setStage(3, 85, "结构嗅探与安全解压中...");
      }, 350);
    };

    xhr.onload = function () {
      try {
        var data = JSON.parse(xhr.responseText);
        if (xhr.status >= 400 || data.ok === false) throw new Error(data.error || "上传失败");
        setStage(4, 100, "制品安全就绪！正在同步画廊...");
        setTimeout(refresh, 500);
      } catch (error) {
        resetDropzone();
        onError(error);
      }
    };

    xhr.onerror = function () {
      resetDropzone();
      onError(new Error("网络错误，上传中断"));
    };

    xhr.send(form);
  }

  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches('input[type="file"][name="cover"]')) return;
    var picker = input.closest(".file-picker");
    var label = picker ? picker.querySelector(".file-name") : null;
    if (label) label.textContent = input.files.length ? input.files[0].name : "未选择";
  });

  var linkUrl = document.getElementById("link-url");
  if (linkUrl) {
    var addLink = document.querySelector('[data-action="add-link"]');
    addLink.addEventListener("click", function () {
      var url = linkUrl.value.trim();
      if (!url) return;
      api("POST", "/projects/link", { url: url, parent_id: parentId() })
        .then(function () {
          linkUrl.value = "";
          refresh();
        })
        .catch(onError);
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
            tip.textContent = "✓ 空间主题已保存生效";
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
        title: appType === "space" ? "新空间" : "",
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
    if (!row) return;

    if (action === "edit") {
      var editor = row.querySelector(".editor");
      editor.hidden = !editor.hidden;
    } else if (action === "save") {
      var payload = {
        title: row.querySelector('[name="title"]').value,
        description: row.querySelector('[name="description"]').value
      };
      var urlInput = row.querySelector('[name="url"]');
      if (urlInput) payload.url = urlInput.value;
      var pwdInput = row.querySelector('[name="password"]');
      if (pwdInput && pwdInput.value.trim() !== "") {
        payload.password = pwdInput.value.trim();
      }
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
            if (!response.ok) throw new Error("封面上传失败");
          });
        })
        .then(refresh)
        .catch(onError);
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
      if (confirm("确定删除该作品？文件将一并删除，不可恢复。")) {
        api("DELETE", "/projects/" + id).then(refresh).catch(onError);
      }
    }
  });
})();
