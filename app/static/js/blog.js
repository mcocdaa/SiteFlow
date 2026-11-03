(function () {
  "use strict";
  var projectId = document.body.dataset.pluginId;
  var base = "/api/admin/projects/" + projectId;
  var csrf = document.querySelector('meta[name="csrf"]').content;
  var status = document.getElementById("save-state");
  var dirty = false;
  var saving = false;

  function t(key) { return window.SiteFlowI18n.t(key); }
  if (status && status.getAttribute("data-i18n")) {
    status.dataset.statusKey = status.getAttribute("data-i18n");
  }
  function message(text, error, statusKey) {
    status.textContent = text;
    status.classList.toggle("is-error", Boolean(error));
    status.setAttribute("role", error ? "alert" : "status");
    status.removeAttribute("data-i18n");
    if (statusKey) {
      status.dataset.statusKey = statusKey;
    } else {
      delete status.dataset.statusKey;
    }
    if (error) { status.focus(); status.scrollIntoView({ block: "center", behavior: "smooth" }); }
  }
  window.addEventListener("siteflow:langchange", function () {
    if (status && status.dataset.statusKey) {
      status.textContent = t(status.dataset.statusKey);
    } else if (status && status.textContent && window.SiteFlowI18n && window.SiteFlowI18n.translateText) {
      status.textContent = window.SiteFlowI18n.translateText(status.textContent);
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
    } catch (error) { throw new Error(t("blog.network_failed")); }
    var data;
    try { data = await response.json(); }
    catch (error) { throw new Error(t("blog.request_failed") + " (HTTP " + response.status + ")"); }
    if (!response.ok || data.ok === false) {
      var detail = data.error || (typeof data.detail === "string" ? data.detail : "");
      throw new Error(detail ? window.SiteFlowI18n.translateText(detail) : t("blog.request_failed") + " (HTTP " + response.status + ")");
    }
    return data;
  }
  document.addEventListener("input", function () {
    dirty = true;
    if (!saving) message(t("blog.unsaved"), false, "blog.unsaved");
  });
  window.addEventListener("beforeunload", function (event) {
    if (dirty) { event.preventDefault(); event.returnValue = ""; }
  });

  var form = document.getElementById("post-form");
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
      new FormData(form).forEach(function (value, key) { payload[key] = value.trim(); });
      payload.tags = payload.tags.split(/[,，]/).map(function (tag) { return tag.trim(); }).filter(Boolean);
      var fields = Array.from(form.elements);
      fields.forEach(function (field) { field.disabled = true; });
      try {
        var slug = document.body.dataset.postSlug;
        var data = await request(slug ? "PATCH" : "POST", base + "/posts" + (slug ? "/" + encodeURIComponent(slug) : ""), payload);
        dirty = false;
        var editUrl = "/admin/projects/" + projectId + "/posts/" + encodeURIComponent(data.post.slug) + "/edit";
        history.replaceState(null, "", editUrl);
        document.body.dataset.postSlug = data.post.slug;
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
  }

  var settings = document.getElementById("blog-settings");
  if (settings) settings.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (saving) return;
    saving = true;
    var button = settings.querySelector("button");
    button.disabled = true;
    message(t("resume.saving"));
    try {
      await request("PATCH", base, {
        title: document.getElementById("f-title").value.trim(),
        description: document.getElementById("f-description").value.trim()
      });
      dirty = false;
      location.reload();
    } catch (error) { message(t("resume.save_failed") + "：" + error.message, true); }
    finally { saving = false; button.disabled = false; }
  });
  document.querySelectorAll("[data-delete-post]").forEach(function (button) {
    button.addEventListener("click", async function () {
      if (!confirm(t("blog.confirm_delete"))) return;
      button.disabled = true;
      try {
        await request("DELETE", base + "/posts/" + encodeURIComponent(button.dataset.deletePost));
        location.reload();
      } catch (error) { message(error.message, true); button.disabled = false; }
    });
  });
})();
