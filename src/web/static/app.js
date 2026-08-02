// Andromeda web shell — client-side JS (U4).
// Minimal for now: EventSource setup, anchor-aware scroll, abort forwarding.
// Expanded in later units (U9 adventure screens, U10 SSE streaming).

(function () {
  "use strict";

  // Anchor-aware scroll: new content scrolls only if the player is at the bottom.
  const spine = document.getElementById("spine");
  if (spine) {
    let wasAtBottom = true;

    spine.addEventListener("scroll", function () {
      wasAtBottom = spine.scrollTop + spine.clientHeight >= spine.scrollHeight - 2;
      spine.classList.toggle("drifted", !wasAtBottom);
    });

    // Expose for htmx after-swap hook (U9/U10 will wire this).
    window.andromedaScrollAnchor = function () {
      if (wasAtBottom) {
        spine.scrollTop = spine.scrollHeight;
      }
    };
  }

  // Drawer tab switching.
  const drawerTabs = document.querySelectorAll(".drawer-tabs button");
  drawerTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      drawerTabs.forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
    });
  });
})();
