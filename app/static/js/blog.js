(function () {
  "use strict";
  var projectId = document.body.dataset.pluginId;
  var base = "/api/admin/projects/" + projectId;
  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var csrf = csrfMeta ? csrfMeta.content : "";
  var status = document.getElementById("save-state");
  var dirty = false;
  var saving = false;

  function t(key) {
    return window.SiteFlowI18n ? window.SiteFlowI18n.t(key) : key;
  }
  function trError(text) {
    if (!text) return "";
    return window.SiteFlowI18n && window.SiteFlowI18n.translateText
      ? window.SiteFlowI18n.translateText(text)
      : text;
  }
  function toast(text, type, key) {
    if (window.SiteFlowToast && window.SiteFlowToast.show) {
      window.SiteFlowToast.show(text, { type: type || "info", key: key || "" });
    }
  }
  function queueToast(text, type, key) {
    if (window.SiteFlowToast && window.SiteFlowToast.queue) {
      window.SiteFlowToast.queue(text, { type: type || "success", key: key || "" });
    }
  }
  if (status && status.getAttribute("data-i18n")) {
    status.dataset.statusKey = status.getAttribute("data-i18n");
  }
  function message(text, error, statusKey) {
    if (!status) {
      if (text) toast(text, error ? "error" : "info", statusKey);
      return;
    }
    status.textContent = text;
    status.classList.toggle("is-error", Boolean(error));
    status.setAttribute("role", error ? "alert" : "status");
    status.removeAttribute("data-i18n");
    if (statusKey) {
      status.dataset.statusKey = statusKey;
    } else {
      delete status.dataset.statusKey;
    }
    if (error) {
      toast(text, "error");
      status.focus();
      status.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }
  window.addEventListener("siteflow:langchange", function () {
    if (status && status.dataset.statusKey) {
      status.textContent = t(status.dataset.statusKey);
    } else if (status && status.textContent) {
      status.textContent = trError(status.textContent);
    }
  });
  async function request(method, url, payload) {
    var response;
    try {
      response = await fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: payload === undefined ? undefined : JSON.stringify(payload)
      });
    } catch (error) {
      throw new Error(t("blog.network_failed"));
    }
    var data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error(t("blog.request_failed") + " (HTTP " + response.status + ")");
    }
    if (!response.ok || data.ok === false) {
      var detail = data.error || (typeof data.detail === "string" ? data.detail : "");
      throw new Error(detail ? trError(detail) : t("blog.request_failed") + " (HTTP " + response.status + ")");
    }
    return data;
  }
  async function uploadExtMedia(extId, kind, file) {
    var formData = new FormData();
    formData.append("file", file);
    formData.append("kind", kind);
    var response;
    try {
      response = await fetch(base + "/extensions/" + encodeURIComponent(extId) + "/media", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
        body: formData
      });
    } catch (error) {
      throw new Error(t("blog.network_failed"));
    }
    var data;
    try {
      data = await response.json();
    } catch (error) {
      throw new Error(t("blog.request_failed") + " (HTTP " + response.status + ")");
    }
    if (!response.ok || data.ok === false) {
      var detail = data.error || (typeof data.detail === "string" ? data.detail : "");
      throw new Error(detail ? trError(detail) : t("blog.request_failed") + " (HTTP " + response.status + ")");
    }
    return data;
  }
  function isSafePreviewUrl(url) {
    if (!url) return false;
    return (
      url.indexOf("https://") === 0 ||
      url.indexOf("http://") === 0 ||
      url.indexOf("/media/blog/") === 0 ||
      url.indexOf("/media/ext/") === 0
    );
  }
  function syncPreview(scope, targetName, value) {
    if (!scope || !targetName) return;
    var preview = scope.querySelector('[data-ext-preview="' + CSS.escape(targetName) + '"]');
    if (!preview) return;
    var cleaned = (value || "").trim();
    if (isSafePreviewUrl(cleaned)) {
      preview.src = cleaned;
      preview.hidden = false;
    } else {
      preview.removeAttribute("src");
      preview.hidden = true;
    }
    var clearBtn = scope.querySelector('[data-ext-clear="' + CSS.escape(targetName) + '"]');
    if (clearBtn && cleaned) clearBtn.hidden = false;
  }

  var form = document.getElementById("post-form");
  var settings = document.getElementById("blog-settings");
  document.addEventListener("input", function (event) {
    var target = event.target;
    if (form && form.contains(target) && target.name) {
      syncPreview(form, target.name, target.value);
    }
    if ((form && form.contains(target)) || (settings && settings.contains(target))) {
      dirty = true;
      if (!saving) message(t("blog.unsaved"), false, "blog.unsaved");
    }
  });
  window.addEventListener("beforeunload", function (event) {
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  if (form) {
    if (!document.body.dataset.postSlug) {
      var now = new Date();
      form.elements.date.value = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
    }
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (saving) return;
      saving = true;
      message(t("resume.saving"));
      var payload = {};
      var meta = {};
      var hasMeta = false;
      new FormData(form).forEach(function (value, key) {
        if (typeof value !== "string") return;
        if (key.indexOf("meta.") === 0) {
          meta[key.slice(5)] = value.trim();
          hasMeta = true;
        } else {
          payload[key] = value.trim();
        }
      });
      if (hasMeta) payload.meta = meta;
      payload.tags = (payload.tags || "").split(/[,，]/).map(function (tag) { return tag.trim(); }).filter(Boolean);
      var fields = Array.from(form.elements);
      fields.forEach(function (field) { field.disabled = true; });
      try {
        var slug = document.body.dataset.postSlug;
        var data = await request(slug ? "PATCH" : "POST", base + "/posts" + (slug ? "/" + encodeURIComponent(slug) : ""), payload);
        dirty = false;
        var editUrl = "/admin/projects/" + projectId + "/posts/" + encodeURIComponent(data.post.slug) + "/edit";
        history.replaceState(null, "", editUrl);
        document.body.dataset.postSlug = data.post.slug;
        if (form.elements.slug) form.elements.slug.value = data.post.slug;
        message(t("blog.saved_label"), false, "blog.saved_label");
        toast(t("blog.saved_title"), "success", "blog.saved_title");
        form.hidden = true;
        var saved = document.getElementById("post-saved");
        saved.hidden = false;
        document.getElementById("saved-post-title").textContent = data.post.title;
        document.getElementById("view-post").href = document.body.dataset.previewUrl + "posts/" + encodeURIComponent(data.post.slug);
        document.getElementById("continue-post").href = editUrl;
        saved.scrollIntoView({ block: "start" });
        document.getElementById("view-post").focus();
      } catch (error) {
        message(t("resume.save_failed") + "：" + error.message, true);
      } finally {
        saving = false;
        fields.forEach(function (field) { field.disabled = false; });
      }
    });
    var continuePost = document.getElementById("continue-post");
    if (continuePost) {
      continuePost.addEventListener("click", function (event) {
        event.preventDefault();
        var saved = document.getElementById("post-saved");
        if (saved) saved.hidden = true;
        form.hidden = false;
        message(t("blog.saved_label"), false, "blog.saved_label");
        form.scrollIntoView({ block: "start" });
      });
    }
  }

  if (settings) {
    settings.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (saving) return;
      saving = true;
      var button = settings.querySelector("button");
      button.disabled = true;
      try {
        await request("PATCH", base, {
          title: document.getElementById("f-title").value.trim(),
          description: document.getElementById("f-description").value.trim()
        });
        dirty = false;
        queueToast(t("blog.settings_saved"), "success", "blog.settings_saved");
        location.reload();
      } catch (error) {
        toast(t("resume.save_failed") + "：" + error.message, "error");
      } finally {
        saving = false;
        button.disabled = false;
      }
    });
  }

  document.querySelectorAll("[data-delete-post]").forEach(function (button) {
    button.addEventListener("click", async function () {
      if (!confirm(t("blog.confirm_delete"))) return;
      button.disabled = true;
      try {
        await request("DELETE", base + "/posts/" + encodeURIComponent(button.dataset.deletePost));
        queueToast(t("blog.post_deleted"), "success", "blog.post_deleted");
        location.reload();
      } catch (error) {
        toast(error.message, "error");
        button.disabled = false;
      }
    });
  });

  if (form) {
    form.addEventListener("click", async function (event) {
      var uploadBtn = event.target.closest("[data-ext-upload]");
      if (uploadBtn) {
        var extId = uploadBtn.dataset.extUpload;
        var kind = uploadBtn.dataset.uploadKind || "cover";
        var targetName = uploadBtn.dataset.uploadTarget;
        var picker = document.createElement("input");
        picker.type = "file";
        picker.accept = uploadBtn.dataset.uploadAccept || "image/*";
        picker.addEventListener("change", async function () {
          if (!picker.files || !picker.files.length) return;
          var origText = uploadBtn.textContent;
          uploadBtn.disabled = true;
          uploadBtn.textContent = t("blog.ext_uploading");
          try {
            var data = await uploadExtMedia(extId, kind, picker.files[0]);
            var input = targetName ? form.querySelector('[name="' + CSS.escape(targetName) + '"]') : null;
            if (input) {
              input.value = data.url || "";
              input.dispatchEvent(new Event("input", { bubbles: true }));
            }
            syncPreview(form, targetName, data.url || "");
          } catch (error) {
            message(error.message, true);
          } finally {
            uploadBtn.disabled = false;
            uploadBtn.textContent = origText;
          }
        });
        picker.click();
        return;
      }

      var clearBtn = event.target.closest("[data-ext-clear]");
      if (clearBtn) {
        var clearTarget = clearBtn.dataset.extClear;
        var clearInput = clearTarget ? form.querySelector('[name="' + CSS.escape(clearTarget) + '"]') : null;
        if (clearInput) {
          clearInput.value = "";
          clearInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        syncPreview(form, clearTarget, "");
      }
    });
  }
})();
