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
  document.body.addEventListener("htmx:afterSwap", function (e) {
    wireDrawerTabs();
    syncDrawerState();

    // U8: Start SSE narration after action/free-text swaps into #spine.
    // Drawer tab loads target .drawer-content and OOB status strips target
    // #status-strip — neither matches, so they don't trigger narration.
    var target = (e.detail && e.detail.target) || {};
    if (target.id === "spine") {
      retryAttempt = 0;
      startNarration();
    }
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

  // -----------------------------------------------------------------
  // SSE narration streaming and guided retry (U8, R14, AE4).
  //
  // After an action swap into #spine, an EventSource streams typed blocks
  // from /stream/{save}/narration.  The client renders narration, change,
  // badge, divider, and error blocks; receipt blocks are skipped (already
  // in the POST fragment).  On ``done`` the source closes and — when an
  // LLM adapter is configured (data-llm-configured="true") — the retry
  // control is revealed with a steering input and attempt counter.  Retry
  // uses fetch + stream reader against /stream/{save}/retry, parsing the
  // same SSE block protocol.
  // -----------------------------------------------------------------

  var MAX_RETRIES = 3;         // mirrors MAX_RETRIES_PER_BEAT (src/game/narration.py)
  var narrationSource = null;   // at most one live EventSource
  var retryAttempt = 0;         // resets to 0 on each action swap into #spine

  function getSaveName() {
    // Prefer the data attribute (always available in the rendered page);
    // fall back to URL parsing for robustness.
    var region = document.getElementById("narration-stream");
    if (region && region.getAttribute("data-save-name")) {
      return region.getAttribute("data-save-name");
    }
    var parts = window.location.pathname.split("/");
    return parts[parts.length - 1] || parts[parts.length - 2] || "";
  }

  function closeNarration() {
    if (narrationSource) {
      narrationSource.close();
      narrationSource = null;
    }
  }

  function renderBlock(data) {
    var region = document.getElementById("narration-stream");
    if (!region) return;

    // receipt: skip — already rendered in the POST fragment.
    // done: skip — handled by stream end / EventSource close.
    if (data.type === "receipt" || data.type === "done") return;

    var el;
    if (data.type === "narration") {
      el = document.createElement("p");
      el.className = "narration-block";
      el.textContent = data.content;
    } else if (data.type === "change") {
      el = document.createElement("p");
      el.className = "change-block";
      el.textContent = data.content;
    } else if (data.type === "badge") {
      el = document.createElement("span");
      el.className = "badge-block";
      el.textContent = data.content;
    } else if (data.type === "divider") {
      el = document.createElement("hr");
      el.className = "divider-block";
    } else if (data.type === "error") {
      el = document.createElement("p");
      el.className = "error-block";
      el.textContent = data.content;
    }
    if (el) region.appendChild(el);

    if (window.andromedaScrollAnchor) window.andromedaScrollAnchor();
  }

  function startNarration() {
    // At most one live source — close any existing one first.
    closeNarration();

    var region = document.getElementById("narration-stream");
    if (region) region.innerHTML = "";

    var saveName = getSaveName();
    if (!saveName) return;

    narrationSource = new EventSource("/stream/" + encodeURIComponent(saveName) + "/narration");

    narrationSource.onmessage = function (event) {
      try {
        var data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (data.type === "done") {
        closeNarration();
        revealRetryControl();
      } else if (data.type === "error") {
        renderBlock(data);
        closeNarration();
        revealRetryControl();
      } else {
        renderBlock(data);
      }
    };

    narrationSource.onerror = function () {
      // Transport-level failure (network drop, server crash).  Show a
      // fallback error and reveal the retry control so the player can
      // attempt a retelling.  If the server already sent an ``error``
      // block, closeNarration() was called in onmessage and the
      // EventSource will not dispatch onerror after explicit close.
      renderBlock({ type: "error", content: "Narration stream interrupted." });
      closeNarration();
      revealRetryControl();
    };
  }

  function revealRetryControl() {
    var region = document.getElementById("narration-stream");
    if (!region) return;

    // Retry affordance renders only when an LLM adapter is configured.
    // Template mode streams blocks identically but hides the control.
    if (document.body.getAttribute("data-llm-configured") !== "true") return;

    // Remove any existing retry control first.
    var existing = region.querySelector(".retry-control");
    if (existing) existing.remove();

    // Cap reached — show the disabled message, no form.
    if (retryAttempt >= MAX_RETRIES) {
      var cap = document.createElement("div");
      cap.className = "retry-control";
      var msg = document.createElement("p");
      msg.className = "retry-disabled";
      msg.textContent = "Retry limit reached (" + MAX_RETRIES + " per beat).";
      cap.appendChild(msg);
      region.appendChild(cap);
      return;
    }

    // Build the retry form.
    var control = document.createElement("div");
    control.className = "retry-control";

    var input = document.createElement("input");
    input.type = "text";
    input.name = "steering_text";
    input.placeholder = "Steer the retelling…";
    input.autocomplete = "off";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Different telling";

    var count = document.createElement("span");
    count.className = "retry-count";
    count.textContent = "Attempt " + (retryAttempt + 1) + " of " + MAX_RETRIES;

    control.appendChild(input);
    control.appendChild(btn);
    control.appendChild(count);
    region.appendChild(control);
    input.focus();

    function submit() {
      var text = input.value;
      retryAttempt++;
      control.remove();
      submitRetry(text);
    }

    btn.addEventListener("click", submit);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
  }

  function submitRetry(steeringText) {
    var saveName = getSaveName();
    if (!saveName) return;

    var region = document.getElementById("narration-stream");
    if (!region) return;

    // Clear previous narration blocks for the retelling.
    var oldBlocks = region.querySelectorAll(
      ".narration-block, .change-block, .divider-block, .badge-block, .error-block"
    );
    oldBlocks.forEach(function (b) { b.remove(); });

    var body = new URLSearchParams();
    body.set("steering_text", steeringText);
    body.set("attempt", String(retryAttempt));

    fetch("/stream/" + encodeURIComponent(saveName) + "/retry", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    }).then(function (response) {
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";

      function processBuffer() {
        // SSE events are separated by blank lines (\n\n).
        var events = buffer.split("\n\n");
        buffer = events.pop(); // keep incomplete tail
        for (var i = 0; i < events.length; i++) {
          var lines = events[i].split("\n");
          for (var j = 0; j < lines.length; j++) {
            if (lines[j].indexOf("data: ") === 0) {
              try {
                var data = JSON.parse(lines[j].slice(6));
              } catch (err) {
                continue;
              }
              if (data.type !== "done") {
                renderBlock(data);
              }
            }
          }
        }
      }

      function pump() {
        reader.read().then(function (result) {
          if (result.done) {
            if (buffer.trim()) processBuffer();
            // Always reveal the retry control on stream end — the
            // attempt counter already prevents over-cap retries.
            revealRetryControl();
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          processBuffer();
          pump();
        });
      }

      pump();
    }).catch(function () {
      // Network error — reveal control so player can retry.
      revealRetryControl();
    });
  }
})();
