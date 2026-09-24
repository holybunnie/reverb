(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const safeRead = (key) => {
    try { return JSON.parse(localStorage.getItem(key) || "{}"); }
    catch { return {}; }
  };
  const safeWrite = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch { return false; }
  };
  const header = $(".site-header");
  $(".menu")?.addEventListener("click", () => header.classList.toggle("open"));

  const clock = $("[data-clock]");
  if (clock) {
    const tick = () => {
      const zone = clock.dataset.zone || "Africa/Lagos";
      try {
        clock.firstChild.nodeValue = new Intl.DateTimeFormat("en-GB", {
          timeZone: zone, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
        }).format(new Date()) + " ";
      } catch { clock.firstChild.nodeValue = "--:--:-- "; }
    };
    tick();
    setInterval(tick, 1000);
  }

  const preferences = $("[data-preferences]");
  if (preferences) {
    const stored = safeRead("reverb.preferences");
    if (stored.risk && !preferences.elements.risk.value) preferences.elements.risk.value = stored.risk;
    if (stored.timezone) preferences.elements.timezone.value = stored.timezone;
    preferences.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = { risk: preferences.elements.risk.value, timezone: preferences.elements.timezone.value };
      if (!safeWrite("reverb.preferences", value)) return;
      const label = $("[data-risk-label]");
      if (label) label.textContent = value.risk ? `$${Number(value.risk).toFixed(2)}` : "Not set";
      const state = $("[data-save-state]");
      if (state) {
        state.textContent = "Saved just now";
        setTimeout(() => { state.textContent = "Saved on this device"; }, 2200);
      }
    });
  }

  const timezonePreference = () => safeRead("reverb.preferences").timezone || "Africa/Lagos";
  const formatTime = (raw, zone) => {
    if (!raw || raw === "unresolved") return "Time not supplied";
    const value = new Date(raw);
    if (Number.isNaN(value.valueOf())) return "Time unavailable";
    try {
      return new Intl.DateTimeFormat("en-GB", {
        timeZone: zone, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
      }).format(value);
    } catch { return "Timezone unavailable"; }
  };
  const formatNewYork = (raw) => formatTime(raw, "America/New_York") + " ET";
  const request = async (url, options = {}) => {
    const response = await fetch(url, { cache: "no-store", ...options });
    let body;
    try { body = await response.json(); }
    catch { throw new Error(`Reverb returned an unreadable response (${response.status}).`); }
    if (!response.ok) throw new Error(body.message || body.result?.explanation || `Request failed (${response.status}).`);
    return body;
  };

  const eventBuilder = $("[data-event-builder]");
  if (eventBuilder) {
    const live = eventBuilder.dataset.liveEvents === "true";
    const search = $("[data-event-search]");
    const list = $("[data-events-list]");
    const status = $("[data-events-status]");
    const empty = $("[data-empty-search]");
    const selectedSummary = $("[data-selected-event-summary]");
    const submit = $("[data-submit-thesis]");
    const form = $("[data-thesis-form]");
    const preview = $("[data-decision-preview]");
    let events = [];
    let selected = safeRead("reverb.selectedEvent");
    let loading = false;

    const basisLabel = (event) => {
      if (event.event_time_basis === "source_exact") return "Calendar time supplied";
      if (event.event_time_basis === "configured_default_assumption") return "16:05 ET default · assumed";
      return "Time unresolved";
    };

    const renderList = () => {
      if (!list) return;
      const needle = (search?.value || "").trim().toLowerCase();
      const visible = events.filter((event) => `${event.company_name || ""} ${event.symbol || ""}`.toLowerCase().includes(needle));
      list.replaceChildren();
      for (const item of visible) {
        const card = document.createElement("button");
        card.type = "button";
        card.className = `event-result${selected?.calendar_event_id === item.calendar_event_id ? " selected" : ""}`;
        card.setAttribute("aria-pressed", selected?.calendar_event_id === item.calendar_event_id ? "true" : "false");
        const avatar = document.createElement("span");
        avatar.className = "ticker-avatar";
        avatar.textContent = (item.symbol || "?").slice(0, 2);
        const name = document.createElement("span");
        name.className = "event-result-name";
        const strong = document.createElement("strong");
        strong.textContent = item.company_name || item.symbol;
        const meta = document.createElement("span");
        meta.textContent = `${item.symbol} · ${item.event_date} · ${basisLabel(item)}`;
        name.append(strong, meta);
        const when = document.createElement("span");
        when.className = "result-time";
        const local = document.createElement("strong");
        local.textContent = formatTime(item.event_at_utc, timezonePreference());
        const ny = document.createElement("span");
        ny.textContent = formatNewYork(item.event_at_utc);
        when.append(local, ny);
        const token = document.createElement("span");
        token.className = `verified-pill token-${String(item.token_status || "unknown").toLowerCase()}`;
        token.textContent = item.token_status === "verified_24_7" ? "TOKEN VERIFIED" :
          item.token_status === "missing" ? "NO TOKEN" : "TOKEN UNVERIFIED";
        card.append(avatar, name, when, token);
        card.addEventListener("click", () => {
          selected = item;
          safeWrite("reverb.selectedEvent", item);
          selectedSummary.textContent = `${item.company_name || item.symbol} (${item.symbol}) · ${formatTime(item.event_at_utc, timezonePreference())} · ${basisLabel(item)}. Reality token: ${item.token_status.replaceAll("_", " ")}.`;
          submit.disabled = false;
          renderList();
        });
        list.append(card);
      }
      if (empty) empty.hidden = !events.length || Boolean(visible.length);
      if (events.length && !visible.length && empty) empty.textContent = "No event matches that company or ticker.";
    };

    const loadEvents = async () => {
      if (!live || loading) return;
      loading = true;
      if (status) status.textContent = "Refreshing the earnings calendar and Reality-token availability…";
      if (submit) submit.disabled = !selected;
      try {
        const body = await request(`/api/events?timezone=${encodeURIComponent(timezonePreference())}`);
        const rows = body.result?.decision?.events;
        if (!Array.isArray(rows)) throw new Error(body.result?.explanation || "The calendar returned no event list.");
        events = rows;
        if (selected) selected = events.find((item) => item.calendar_event_id === selected.calendar_event_id) || null;
        if (selected) {
          selectedSummary.textContent = `${selected.company_name || selected.symbol} (${selected.symbol}) · ${formatTime(selected.event_at_utc, timezonePreference())} · ${basisLabel(selected)}. Reality token: ${selected.token_status.replaceAll("_", " ")}.`;
        }
        if (status) status.textContent = events.length
          ? `${events.length} calendar event${events.length === 1 ? "" : "s"} found. Times marked assumed are not issuer-confirmed.`
          : "No earnings events were returned for this week.";
        renderList();
      } catch (error) {
        events = [];
        renderList();
        if (status) status.textContent = `${error.message} Refresh to retry; no event was fabricated.`;
      } finally {
        loading = false;
        if (submit) submit.disabled = !selected;
      }
    };

    if (live) {
      loadEvents();
      search?.addEventListener("input", renderList);
      $("[data-refresh-events]")?.addEventListener("click", loadEvents);
      const draft = safeRead("reverb.thesisDraft");
      if (draft.direction) {
        const directionInput = $(`input[name="direction"][value="${CSS.escape(draft.direction)}"]`, form);
        if (directionInput) directionInput.checked = true;
      }
      if (draft.move) form.elements.move.value = draft.move;
      if (draft.budget) form.elements.budget.value = draft.budget;
      if (draft.view) form.elements.view.value = draft.view;
      if (!draft.budget && safeRead("reverb.preferences").risk) form.elements.budget.value = safeRead("reverb.preferences").risk;
      const updateDirectionFields = () => {
        const watchOnly = form.elements.direction.value === "watch";
        form.elements.move.required = !watchOnly;
        form.elements.budget.required = !watchOnly;
        form.elements.move.disabled = watchOnly;
        form.elements.budget.disabled = watchOnly;
      };
      form.addEventListener("change", updateDirectionFields);
      updateDirectionFields();
      form?.addEventListener("input", () => safeWrite("reverb.thesisDraft", Object.fromEntries(new FormData(form))));
      let pendingExtraction = null;
      form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!selected || loading || !form.reportValidity()) return;
        const values = Object.fromEntries(new FormData(form));
        const payload = {
          symbol: selected.symbol,
          event_date: selected.event_date,
          calendar_event_id: selected.calendar_event_id,
          direction: values.direction,
          expected_move_percent: values.move ? String(values.move) : "",
          max_loss: values.budget ? String(values.budget) : "",
          user_timezone: timezonePreference(),
          view_text: String(values.view || "").trim().slice(0, 2000),
        };
        const button = $("[data-submit-thesis]", form);
        button.disabled = true;
        button.textContent = "Extracting candidate claims…";
        try {
          const body = await request("/api/thesis/extract", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              symbol: selected.symbol, event_date: selected.event_date,
              calendar_event_id: selected.calendar_event_id, thesis_text: payload.view_text,
            }),
          });
          const result = body.result;
          if (!Array.isArray(result?.claims) || result.claims.length === 0) throw new Error("No candidate claims were returned; revise the thesis and retry.");
          pendingExtraction = { payload, event: selected, result, saved_at: new Date().toISOString() };
          form.hidden = true;
          preview.hidden = false;
          $("[data-decision-status]").textContent = "CANDIDATE CLAIMS · NOT FROZEN";
          $("[data-decision-title]").textContent = `${selected.company_name || selected.symbol} · thesis review`;
          $("[data-decision-copy]").textContent = `Qwen ${result.model} returned ${result.claims.length} candidate claim${result.claims.length === 1 ? "" : "s"}. Read every line. This is not a score, recommendation, or order.`;
          const claimList = $("[data-claims-review]");
          claimList.replaceChildren();
          for (const claim of result.claims) {
            const item = document.createElement("li");
            const label = document.createElement("label");
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.dataset.claimId = claim.claim_id;
            checkbox.setAttribute("aria-label", `Confirm claim: ${claim.text}`);
            const text = document.createElement("span");
            text.textContent = claim.text;
            const meta = document.createElement("small");
            meta.textContent = `${claim.variable} · ${claim.comparison.replaceAll("_", " ")} · ${claim.claim_type.replaceAll("_", " ")}`;
            label.append(checkbox, text);
            item.append(label, meta);
            claimList.append(item);
          }
          $("[data-claim-save-status]").textContent = `Extraction trace: ${result.output_sha256.slice(0, 12)}… · nothing frozen.`;
        } catch (error) {
          if (status) status.textContent = `${error.message} The extraction did not freeze or score the thesis.`;
        } finally {
          button.disabled = false;
          button.innerHTML = 'Extract claims for review <span>→</span>';
        }
      });
      $("[data-edit-thesis]")?.addEventListener("click", () => {
        pendingExtraction = null;
        preview.hidden = true;
        form.hidden = false;
      });
      $("[data-confirm-claims]")?.addEventListener("click", () => {
        const checked = $$("[data-claims-review] input[type=checkbox]");
        const message = $("[data-claim-save-status]");
        if (!pendingExtraction || !checked.length) {
          message.textContent = "Extract candidate claims again before saving a draft.";
          return;
        }
        if (checked.some((input) => !input.checked)) {
          message.textContent = "Confirm every extracted claim, or revise your thesis and extract again.";
          return;
        }
        const saved = {
          ...pendingExtraction,
          claims_confirmed: true,
          workflow_status: "draft_not_frozen",
          confirmed_at: new Date().toISOString(),
        };
        if (!safeWrite("reverb.activeThesis", saved)) {
          message.textContent = "This browser could not save the local draft. Check device storage and try again.";
          return;
        }
        safeWrite("reverb.thesisDraft", {});
        message.textContent = "Saved on this device. Still not frozen: source references, the knowledge snapshot, capture plan, and a committed hash are required before the report.";
      });
    }
  }

  const waiting = $("[data-waiting-state]");
  if (waiting) {
    const active = safeRead("reverb.activeThesis");
    const details = $("[data-waiting-details]");
    const empty = $("[data-waiting-empty]");
    const monitor = $("[data-monitor-reaction]");
    let timer;
    if (active?.event && active?.payload) {
      const event = active.event;
      const result = active.result || null;
      const decision = result?.decision || {};
      const eventAt = event.event_at_utc && event.event_at_utc !== "unresolved" ? new Date(event.event_at_utc) : null;
      $("[data-waiting-title]").textContent = `${event.company_name || event.symbol} · ${event.symbol}`;
      $("[data-waiting-local]").textContent = formatTime(event.event_at_utc, timezonePreference());
      $("[data-waiting-ny]").textContent = formatNewYork(event.event_at_utc);
      $("[data-waiting-basis]").textContent = event.event_time_basis === "source_exact" ? "Source supplied" :
        event.event_time_basis === "configured_default_assumption" ? "16:05 ET · assumed" : "Unresolved";
      $("[data-waiting-budget]").textContent = active.payload.max_loss ? `$${active.payload.max_loss} USDT` : "Not set";
      $("[data-waiting-status]").textContent = result
        ? `${String(result.status).toUpperCase()} · NO ORDER`
        : "THESIS DRAFT · NOT FROZEN";
      $("[data-waiting-status]").classList.add("status-held");
      empty.hidden = true;
      details.hidden = false;
      if (monitor) monitor.hidden = !result?.decision_id;
      const countdown = $("[data-countdown]");
      const tick = () => {
        if (!eventAt || Number.isNaN(eventAt.valueOf())) {
          countdown.textContent = "Time unresolved";
          monitor.disabled = true;
          return;
        }
        const remaining = eventAt.valueOf() - Date.now();
        if (remaining > 0) {
          const total = Math.floor(remaining / 1000);
          const days = Math.floor(total / 86400);
          const hours = Math.floor((total % 86400) / 3600);
          const minutes = Math.floor((total % 3600) / 60);
          const seconds = total % 60;
          countdown.textContent = days ? `${days}d ${hours}h ${minutes}m` : `${hours}h ${minutes}m ${seconds}s`;
          monitor.disabled = true;
        } else {
          countdown.textContent = result?.decision_id
            ? "Event time reached · monitor the reaction"
            : "Event time reached · capture and freeze the research record";
          monitor.disabled = !result?.decision_id;
        }
      };
      tick();
      timer = setInterval(tick, 1000);
      monitor?.addEventListener("click", async () => {
        if (!result?.decision_id || !eventAt || Date.now() < eventAt.valueOf()) return;
        monitor.disabled = true;
        const output = $("[data-monitor-result]");
        output.textContent = "Checking the post-event price path…";
        try {
          const body = await request("/api/react", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ decision_id: result.decision_id }),
          });
          const result = body.result;
          const move = result.arithmetic?.move_pct;
          output.textContent = `${String(result.status).toUpperCase()}: ${result.explanation}${move ? ` Observed move: ${move}.` : ""} Recorded locally; no order was submitted.`;
        } catch (error) {
          output.textContent = `${error.message} No order was submitted.`;
        } finally {
          monitor.disabled = false;
        }
      });
    } else {
      $("[data-waiting-status]").textContent = "NO EVENT SELECTED";
    }
  }

  $$(".magnetic").forEach((element) => {
    element.addEventListener("pointermove", (event) => {
      const rect = element.getBoundingClientRect();
      element.style.transform = `translate(${(event.clientX - rect.left - rect.width / 2) * .06}px, ${(event.clientY - rect.top - rect.height / 2) * .08}px)`;
    });
    element.addEventListener("pointerleave", () => { element.style.transform = ""; });
  });
})();
