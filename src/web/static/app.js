// Andromeda web shell — client-side JS (U4).
// Minimal for now: EventSource setup, anchor-aware scroll, abort forwarding.
// Expanded in later units (U9 adventure screens, U10 SSE streaming,
// U17 drawer disclosure semantics — toggle, Esc, focus return).

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

  // -----------------------------------------------------------------
  // Drawer tab switching (U4).
  // -----------------------------------------------------------------
  function wireDrawerTabs() {
    var drawerTabs = document.querySelectorAll(".drawer-tabs button");
    drawerTabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        drawerTabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
      });
    });
  }

  wireDrawerTabs();

  // -----------------------------------------------------------------
  // Drawer disclosure: toggle, Esc close, focus return (U17 quality floor).
  // State is tracked in ``drawerOpen`` so it survives htmx OOB swaps.
  // -----------------------------------------------------------------
  var initDrawer = document.getElementById("drawer");
  var drawerOpen = initDrawer ? !initDrawer.hasAttribute("hidden") : false;

  function toggleDrawer(forceState) {
    var drawer = document.getElementById("drawer");
    var trigger = document.getElementById("drawer-toggle");
    if (!drawer || !trigger) return;

    var willOpen = forceState !== undefined
      ? forceState
      : drawer.hasAttribute("hidden");

    if (willOpen) {
      drawer.removeAttribute("hidden");
      trigger.setAttribute("aria-expanded", "true");
      drawerOpen = true;
      // Focus the drawer's first focusable element (first tab or close btn).
      var firstFocusable = drawer.querySelector("button, a, input, select");
      if (firstFocusable) firstFocusable.focus();
    } else {
      drawer.setAttribute("hidden", "");
      trigger.setAttribute("aria-expanded", "false");
      drawerOpen = false;
      trigger.focus();
    }
  }

  // Re-apply drawer state after htmx OOB swaps replace #drawer and #drawer-toggle.
  // Server-managed drawers (lifepath drawer_pinned, marked with
  // data-drawer-pinned) read from the swapped DOM so the server's phase-driven
  // open/close wins.  Client-managed drawers (adventure) re-apply the tracked
  // client state so a user-initiated toggle is not reset by the swap.
  function syncDrawerState() {
    var drawer = document.getElementById("drawer");
    var trigger = document.getElementById("drawer-toggle");
    if (!drawer || !trigger) return;
    if (drawer.hasAttribute("data-drawer-pinned")) {
      drawerOpen = !drawer.hasAttribute("hidden");
      return;
    }
    if (drawerOpen) {
      drawer.removeAttribute("hidden");
      trigger.setAttribute("aria-expanded", "true");
    } else {
      drawer.setAttribute("hidden", "");
      trigger.setAttribute("aria-expanded", "false");
    }
  }

  // Re-wire tabs and sync drawer state after htmx OOB swaps.
  document.body.addEventListener("htmx:afterSwap", function () {
    wireDrawerTabs();
    syncDrawerState();
  });

  // Drawer toggle — delegated on document so it survives OOB swaps.
  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "drawer-toggle") {
      toggleDrawer();
    }
  });

  // Close button inside the drawer.
  document.addEventListener("click", function (e) {
    if (e.target && e.target.classList && e.target.classList.contains("drawer-close")) {
      toggleDrawer(false);
    }
  });

  // Esc closes the drawer and returns focus to the trigger.
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var drawer = document.getElementById("drawer");
      if (drawer && !drawer.hasAttribute("hidden")) {
        toggleDrawer(false);
      }
    }
  });
})();
