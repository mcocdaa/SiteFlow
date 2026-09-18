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
  var appUploadMode = false;

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
      uploadFile(fileInput.files[0], { asApp: appUploadMode });
      appUploadMode = false;
      fileInput.value = "";
    });
  }

  function parentId() {
    var value = document.body.getAttribute("data-parent-id");
    return value ? parseInt(value, 10) : null;
  }

  function uploadFile(file, options) {
    options = options || {};
    var form = new FormData();
    form.append("file", file);
    var parent = parentId();
    if (parent) form.append("parent_id", String(parent));
    if (options.asApp) {
      form.append("as_app", "true");
      var titleInput = document.getElementById("app-title");
      if (titleInput && titleInput.value.trim()) form.append("title", titleInput.value.trim());
    }
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/admin/projects/upload");
    xhr.setRequestHeader("X-CSRF-Token", CSRF);
    xhr.onload = function () {
      try {
        var data = JSON.parse(xhr.responseText);
        if (xhr.status >= 400 || data.ok === false) throw new Error(data.error || "上传失败");
        refresh();
      } catch (error) { onError(error); }
    };
    xhr.onerror = function () { onError(new Error("网络错误")); };
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
      var typeSelect = document.getElementById("app-type");
      var titleInput = document.getElementById("app-title");
      api("POST", "/projects/app", {
        type: typeSelect ? typeSelect.value : "space",
        title: titleInput ? titleInput.value.trim() : "",
        parent_id: parentId()
      }).then(refresh).catch(onError);
      return;
    }
    if (action === "upload-app") {
      appUploadMode = true;
      if (fileInput) fileInput.click();
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
