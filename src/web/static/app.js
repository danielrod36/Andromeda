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
  // State is tracked in ``drawerOpen`` so it survives htmx swaps.
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

  // U5: the drawer is client-managed — never OOB-swapped.  The lifepath
  // pin state travels as a ``data-drawer-pinned`` attribute on the OOB
  // status strip.  On each ``htmx:afterSwap`` we read that attribute and
  // open/close the drawer to match the server's phase-driven pin, without
  // touching the drawer's loaded tab content.  Adventure has no pin
  // attribute → the drawer's client state is left untouched.
  function syncDrawerState() {
    var strip = document.getElementById("status-strip");
    var drawer = document.getElementById("drawer");
    var trigger = document.getElementById("drawer-toggle");
    if (!strip || !drawer || !trigger) return;

    if (!strip.hasAttribute("data-drawer-pinned")) {
      // Adventure: fully client-managed — no server-driven pin.  The OOB
      // swap replaced #drawer-toggle (hardcoded aria-expanded="false"), so
      // resync its aria-expanded from the live drawer state before leaving.
      trigger.setAttribute("aria-expanded", drawerOpen ? "true" : "false");
      return;
    }

    var pinned = strip.getAttribute("data-drawer-pinned") === "true";
    if (pinned) {
      drawer.removeAttribute("hidden");
      trigger.setAttribute("aria-expanded", "true");
      drawerOpen = true;
    } else {
      drawer.setAttribute("hidden", "");
      trigger.setAttribute("aria-expanded", "false");
      drawerOpen = false;
    }
  }

  // Re-wire tabs and sync drawer state after htmx swaps.
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

  // U7: Pill links open the drawer before the htmx request fires, so the
  // audit fragment lands in a visible panel.  Delegated on document so it
  // survives spine swaps.
  document.addEventListener("click", function (e) {
    var target = e.target.closest ? e.target.closest("a.pill-link") : null;
    if (target) {
      toggleDrawer(true);
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
