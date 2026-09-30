(function () {
  "use strict";

  var modal = document.getElementById("preview-modal");
  if (!modal) return;

  var frame = document.getElementById("preview-frame");
  var box = document.getElementById("preview-box");
  var loader = document.getElementById("preview-loader");
  var titleEl = document.getElementById("preview-title");
  var badgeEl = document.getElementById("preview-badge");
  var openLink = document.getElementById("preview-open-link");
  var rotateBtn = document.getElementById("preview-rotate");
  var qrToggle = document.getElementById("preview-qr-toggle");
  var qrPopover = document.getElementById("qr-popover");
  var qrBackdrop = document.getElementById("qr-backdrop");
  var qrImgWrap = document.getElementById("qr-img-wrap");
  var qrUrlText = document.getElementById("qr-url-text");
  var qrClose = document.getElementById("qr-close");
  var viewportBtns = modal.querySelectorAll(".preview-vbtn[data-vp]");

  var currentSlug = "";
  var currentVp = "100%";
  var isRotated = false;

  function closeQr() {
    if (qrPopover) qrPopover.hidden = true;
    if (qrBackdrop) qrBackdrop.hidden = true;
  }

  function setViewport(vp) {
    closeQr();
    currentVp = vp;
    isRotated = false;
    viewportBtns.forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-vp") === vp);
    });

    if (vp === "100%") {
      box.style.width = "100%";
      box.style.height = "100%";
      rotateBtn.hidden = true;
    } else if (vp === "768px") {
      box.style.width = "768px";
      box.style.height = "100%";
      rotateBtn.hidden = false;
    } else if (vp === "375px") {
      box.style.width = "375px";
      box.style.height = "100%";
      rotateBtn.hidden = false;
    }
  }

  function toggleRotate() {
    closeQr();
    isRotated = !isRotated;
    if (currentVp === "768px") {
      box.style.width = isRotated ? "1024px" : "768px";
    } else if (currentVp === "375px") {
      box.style.width = isRotated ? "667px" : "375px";
    }
  }

  function openPreview(slug, title, type) {
    currentSlug = slug;
    titleEl.textContent = title || slug;
    badgeEl.textContent = (type || "HTML").toUpperCase();
    var projectUrl = "/projects/" + slug + "/";
    openLink.href = projectUrl;
    openLink.target = "_blank";

    setViewport("100%");
    closeQr();
    loader.hidden = false;

    frame.onload = function () {
      loader.hidden = true;
    };
    frame.src = projectUrl;

    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closePreview() {
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    frame.src = "about:blank";
    closeQr();
    document.body.style.overflow = "";
  }

  function loadQr() {
    if (!qrPopover.hidden) {
      closeQr();
      return;
    }
    qrPopover.hidden = false;
    if (qrBackdrop) qrBackdrop.hidden = false;

    var fullUrl = location.origin + "/projects/" + currentSlug + "/";
    qrUrlText.textContent = fullUrl;
    qrImgWrap.innerHTML = '<div class="qr-loading">生成二维码中...</div>';

    fetch("/api/qrcode?url=" + encodeURIComponent(fullUrl))
      .then(function (res) {
        if (!res.ok) throw new Error("二维码生成失败");
        return res.text();
      })
      .then(function (svgHtml) {
        qrImgWrap.innerHTML = svgHtml;
      })
      .catch(function (err) {
        qrImgWrap.innerHTML = '<div class="qr-error">' + (err.message || "无法加载") + '</div>';
      });
  }

  // Viewport buttons
  viewportBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setViewport(btn.getAttribute("data-vp"));
    });
  });

  if (rotateBtn) rotateBtn.addEventListener("click", toggleRotate);
  if (qrToggle) qrToggle.addEventListener("click", loadQr);
  if (qrClose) qrClose.addEventListener("click", closeQr);
  if (qrBackdrop) qrBackdrop.addEventListener("click", closeQr);

  // Close handlers
  modal.addEventListener("click", function (e) {
    if (e.target.closest('[data-action="close-preview"]')) {
      closePreview();
    }
  });

  document.addEventListener("click", function (e) {
    if (!qrPopover.hidden && !qrPopover.contains(e.target) && !qrToggle.contains(e.target)) {
      closeQr();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.hidden) {
      if (!qrPopover.hidden) {
        closeQr();
      } else {
        closePreview();
      }
    }
  });

  // Global listener for preview buttons
  document.addEventListener("click", function (e) {
    var trigger = e.target.closest('[data-action="quick-preview"], [data-action="preview"]');
    if (!trigger) return;
    e.preventDefault();
    e.stopPropagation();

    var slug = trigger.getAttribute("data-slug");
    var title = trigger.getAttribute("data-title");
    var type = trigger.getAttribute("data-type") || "html";
    if (!slug) {
      var row = trigger.closest("[data-id], .card");
      if (row) {
        slug = row.getAttribute("data-slug");
        title = row.getAttribute("data-title") || title;
        type = row.getAttribute("data-type") || type;
      }
    }
    if (slug) {
      openPreview(slug, title, type);
    }
  });

  window.SiteFlowPreview = { open: openPreview, close: closePreview };
})();
