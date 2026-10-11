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
  const formatNewYork = (raw) => (!raw || raw === "unresolved") ? "" : formatTime(raw, "America/New_York") + " ET";
  const tokenLabel = (status) => status === "verified_24_7" ? "24/7 trading verified" :
    status === "online_reality_unverified_24_7" ? "online; 24/7 hours not verified" :
    status === "missing" ? "not listed" : String(status || "unknown").replaceAll("_", " ");
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

    const whenLabel = (event) => (!event.event_at_utc || event.event_at_utc === "unresolved")
      ? `${event.event_date} · release time not yet published`
      : `${formatTime(event.event_at_utc, timezonePreference())} · ${basisLabel(event)}`;

    const bitgetPanel = $("[data-bitget-context]");
    let bitgetRequest = 0;
    const SESSIONS = { after_close: "after the close", before_open: "before the open", during_market: "during market hours", unspecified: "session not given" };
    const shortDate = (iso) => new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));
    const usd = (value) => {
      const number = Number(value);
      if (!Number.isFinite(number)) return "—";
      const size = Math.abs(number);
      if (size >= 1e9) return `$${(number / 1e9).toFixed(2)}B`;
      if (size >= 1e6) return `$${(number / 1e6).toFixed(1)}M`;
      return `$${number.toFixed(2)}`;
    };
    const setPart = (selector, text, tone = "") => {
      const node = $(selector, bitgetPanel);
      node.textContent = text;
      node.className = tone;
    };
    const renderBitgetContext = (context) => {
      const calendar = context.calendar || {};
      if (calendar.status === "agrees" || calendar.status === "differs") {
        const when = `${shortDate(calendar.bitget_release_date)}, ${SESSIONS[calendar.bitget_session] || calendar.bitget_session}`;
        setPart("[data-bitget-calendar]", calendar.status === "agrees"
          ? `${when} · agrees with this week's calendar`
          : `${when} · ${Math.abs(calendar.difference_days)} day(s) from this week's calendar; check the issuer's own site`,
          calendar.status);
      } else {
        setPart("[data-bitget-calendar]", calendar.status === "not_listed" ? "Release not listed by Bitget" : `Unavailable: ${calendar.detail || "no answer"}`);
      }
      const quote = context.quote || {};
      if (quote.status === "ok") {
        const change = Number(quote.change_pct);
        setPart("[data-bitget-quote]", `${usd(quote.last_price)} (${change >= 0 ? "+" : ""}${change.toFixed(2)}%)${quote.market_cap ? ` · market cap ${usd(quote.market_cap)}` : ""}`);
      } else {
        setPart("[data-bitget-quote]", `Unavailable: ${quote.detail || "no answer"}`);
      }
      const consensus = context.consensus || {};
      if (consensus.status === "current" && consensus.estimates.length) {
        const parts = consensus.estimates.map((item) => {
          const value = item.indicator === "EPS" ? `$${Number(item.mean).toFixed(2)}` : usd(item.mean);
          const range = item.low && item.high ? `, range ${item.indicator === "EPS" ? `$${Number(item.low).toFixed(2)}–$${Number(item.high).toFixed(2)}` : `${usd(item.low)}–${usd(item.high)}`}` : "";
          return `${item.indicator} ${value}${item.analysts ? ` (${item.analysts} analysts${range})` : range ? ` (${range.slice(2)})` : ""}`;
        });
        const first = consensus.estimates[0];
        setPart("[data-bitget-consensus]", `${parts.join(" · ")} · quarter ending ${consensus.quarter_end_month} · ${first.upstream_source || "upstream"} via Bitget, scraped ${shortDate(first.scraped_on)}`);
      } else {
        const reasons = {
          stale: `Not shown: the newest estimate is from ${consensus.newest_scrape ? shortDate(consensus.newest_scrape) : "too long ago"}.`,
          post_release_only: "Not shown: every estimate for this quarter was collected after the release.",
          not_listed: "No consensus listed for this quarter.",
        };
        setPart("[data-bitget-consensus]", reasons[consensus.status] || `Unavailable: ${consensus.detail || "no answer"}`);
      }
      $("[data-bitget-fetched]", bitgetPanel).textContent = `Fetched ${formatTime(context.fetched_at, timezonePreference())}`;
    };
    const loadBitgetContext = async (item) => {
      if (!bitgetPanel || !live || !item?.symbol || !item?.event_date) return;
      const ticket = ++bitgetRequest;
      bitgetPanel.hidden = false;
      for (const selector of ["[data-bitget-calendar]", "[data-bitget-quote]", "[data-bitget-consensus]"]) setPart(selector, "Asking Bitget…");
      $("[data-bitget-fetched]", bitgetPanel).textContent = "";
      try {
        const body = await request(`/api/events/context?symbol=${encodeURIComponent(item.symbol)}&date=${encodeURIComponent(item.event_date)}`);
        if (ticket === bitgetRequest) renderBitgetContext(body.result);
      } catch (error) {
        if (ticket !== bitgetRequest) return;
        for (const selector of ["[data-bitget-calendar]", "[data-bitget-quote]", "[data-bitget-consensus]"]) setPart(selector, "Unavailable");
        $("[data-bitget-fetched]", bitgetPanel).textContent = `${error.message} Nothing was filled in.`;
      }
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
        meta.textContent = `${item.symbol} · ${item.event_date}${item.event_at_utc && item.event_at_utc !== "unresolved" ? ` · ${basisLabel(item)}` : ""}`;
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
          item.token_status === "missing" ? "NO TOKEN" : "TOKEN ONLINE";
        card.append(avatar, name, when, token);
        card.addEventListener("click", () => {
          selected = item;
          safeWrite("reverb.selectedEvent", item);
          selectedSummary.textContent = `${item.company_name || item.symbol} (${item.symbol}) · ${whenLabel(item)}. Reality token: ${tokenLabel(item.token_status)}.`;
          submit.disabled = false;
          renderList();
          loadBitgetContext(item);
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
          selectedSummary.textContent = `${selected.company_name || selected.symbol} (${selected.symbol}) · ${whenLabel(selected)}. Reality token: ${tokenLabel(selected.token_status)}.`;
          loadBitgetContext(selected);
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

  const humanReview = $("[data-human-review]");
  humanReview?.addEventListener("click", () => {
    const status = $("[data-human-review-status]");
    const reviewedAt = new Date().toISOString();
    if (safeWrite("reverb.costcoBriefReview", { reviewed_at: reviewedAt, order_submitted: false })) {
      humanReview.disabled = true;
      humanReview.textContent = "Brief reviewed";
      if (status) status.textContent = `Reviewed at ${reviewedAt}`;
    } else if (status) {
      status.textContent = "Could not save the review locally.";
    }
  });

  $$(".magnetic").forEach((element) => {
    element.addEventListener("pointermove", (event) => {
      const rect = element.getBoundingClientRect();
      element.style.transform = `translate(${(event.clientX - rect.left - rect.width / 2) * .06}px, ${(event.clientY - rect.top - rect.height / 2) * .08}px)`;
    });
    element.addEventListener("pointerleave", () => { element.style.transform = ""; });
  });
})();
