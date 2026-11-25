(() => {
  const banners = document.querySelectorAll("[data-space-banner]");
  banners.forEach((banner) => {
    const key = banner.getAttribute("data-banner-key") || "";
    if (key) {
      try {
        if (window.sessionStorage.getItem(key) === "1") {
          banner.hidden = true;
          return;
        }
      } catch (_err) {
      }
    }
    const closeBtn = banner.querySelector("[data-banner-dismiss]");
    if (!closeBtn) return;
    closeBtn.addEventListener("click", () => {
      banner.hidden = true;
      if (key) {
        try {
          window.sessionStorage.setItem(key, "1");
        } catch (_err) {
        }
      }
    });
  });
})();
