(function () {
  "use strict";

  var DESKTOP_QUERY = "(min-width: 1120px)";
  var ACTIVE_OFFSET = 104;

  function renderMath() {
    if (!window.katex || typeof window.katex.render !== "function") {
      return;
    }
    var nodes = document.querySelectorAll(".sf-math");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.dataset.mathRendered === "1") {
        continue;
      }
      var tex = el.textContent || "";
      el.dataset.mathRendered = "1";
      try {
        window.katex.render(tex, el, {
          displayMode: el.dataset.mathDisplay === "1",
          throwOnError: false,
          strict: "ignore",
          trust: false,
          maxSize: 500,
          maxExpand: 1000
        });
      } catch (e) {
        el.textContent = tex;
      }
    }
  }

  function decodeAnchorId(href) {
    if (!href || href.charAt(0) !== "#") {
      return "";
    }
    var raw = href.slice(1);
    try {
      return decodeURIComponent(raw);
    } catch (e) {
      return raw;
    }
  }

  function initToc() {
    var tocBox = document.querySelector("details.toc-box[data-toc-box]");
    var links = Array.prototype.slice.call(document.querySelectorAll("[data-toc-link]"));
    var mq = window.matchMedia ? window.matchMedia(DESKTOP_QUERY) : null;

    function isDesktop() {
      return mq ? mq.matches : window.innerWidth >= 1120;
    }

    function syncTocOpen() {
      if (tocBox) {
        tocBox.open = isDesktop();
      }
    }

    syncTocOpen();
    if (mq) {
      if (typeof mq.addEventListener === "function") {
        mq.addEventListener("change", syncTocOpen);
      } else if (typeof mq.addListener === "function") {
        mq.addListener(syncTocOpen);
      }
    }

    if (!links.length) {
      return;
    }

    var items = [];
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      var id = decodeAnchorId(link.getAttribute("href") || "");
      var target = id ? document.getElementById(id) : null;
      if (target) {
        items.push({ link: link, target: target });
      }
      link.addEventListener("click", function () {
        if (tocBox && !isDesktop()) {
          tocBox.open = false;
        }
      });
    }

    if (!items.length) {
      return;
    }

    var activeIndex = -1;
    var ticking = false;
    var tocContainer = tocBox ? tocBox.closest(".post-toc") : null;

    function setActive(index) {
      if (index === activeIndex) {
        return;
      }
      activeIndex = index;
      for (var j = 0; j < items.length; j++) {
        var isCurrent = j === index;
        items[j].link.classList.toggle("is-active", isCurrent);
        if (isCurrent) {
          items[j].link.setAttribute("aria-current", "location");
        } else {
          items[j].link.removeAttribute("aria-current");
        }
      }
      if (tocContainer && isDesktop() && index >= 0) {
        var activeEl = items[index].link;
        var containerRect = tocContainer.getBoundingClientRect();
        var itemRect = activeEl.getBoundingClientRect();
        if (itemRect.top < containerRect.top + 24) {
          tocContainer.scrollTop += itemRect.top - containerRect.top - 24;
        } else if (itemRect.bottom > containerRect.bottom - 24) {
          tocContainer.scrollTop += itemRect.bottom - containerRect.bottom + 24;
        }
      }
    }

    function updateActive() {
      ticking = false;
      var scrollBottom = window.innerHeight + window.scrollY;
      var docHeight = document.documentElement.scrollHeight;
      if (docHeight > window.innerHeight && scrollBottom >= docHeight - 8) {
        setActive(items.length - 1);
        return;
      }
      var current = 0;
      for (var k = 0; k < items.length; k++) {
        if (items[k].target.getBoundingClientRect().top <= ACTIVE_OFFSET) {
          current = k;
        } else {
          break;
        }
      }
      setActive(current);
    }

    function scheduleUpdate() {
      if (ticking) {
        return;
      }
      ticking = true;
      window.requestAnimationFrame(updateActive);
    }

    window.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate, { passive: true });
    window.addEventListener("hashchange", scheduleUpdate);
    updateActive();
  }

  function init() {
    renderMath();
    initToc();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
