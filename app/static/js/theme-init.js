(function () {
  "use strict";
  try {
    var theme = localStorage.getItem("sf_theme");
    if (theme) {
      document.documentElement.setAttribute("data-theme", theme);
    }
  } catch (e) {}
})();
