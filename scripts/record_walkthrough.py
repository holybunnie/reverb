"""Screen-record the deployed research-task walkthrough with captions and optional narration.

Drives headless Chromium through all eight steps, overlays one caption per beat,
and writes an MP4, an .srt caption file, and a timestamped shot list. With
--voice, every beat's spoken line is synthesised first (Piper, offline) and the
beat is held on screen until its line has finished, so voice, caption and page
cannot drift apart. Spoken numbers are checked against the committed evidence
before anything is recorded. Playwright, ffmpeg and Piper live in a scratch
environment; none is a project dependency.

    python scripts/record_walkthrough.py [--url URL] [--out DIR] [--voice en_US-ryan-high.onnx]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reverb.walkthrough import walkthrough_data  # noqa: E402
from reverb.walkthrough_stz import walkthrough_data as stz_walkthrough_data  # noqa: E402
from reverb.walkthrough_apld import walkthrough_data as apld_walkthrough_data  # noqa: E402

DEFAULT_URL = "https://holybunnie.github.io/reverb/walkthrough/"
NAME = "research-task-costco"
STZ_URL = "https://holybunnie.github.io/reverb/walkthrough/stz/"
STZ_NAME = "research-task-stz"
APLD_URL = "https://holybunnie.github.io/reverb/walkthrough/apld/"
APLD_NAME = "research-task-apld"
TAIL_SECONDS = 0.8  # pause after each spoken line before the next beat

CAPTION_JS = """text => {
  let el = document.getElementById('rec-caption');
  if (!el) {
    el = document.createElement('div'); el.id = 'rec-caption';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:88%;z-index:99;' +
      'background:rgba(10,12,16,.88);color:#fff;font:600 22px/1.4 system-ui,sans-serif;padding:12px 20px;border-radius:12px;text-align:center';
    document.body.appendChild(el);
  }
  el.textContent = text;
}"""


def check_spoken_numbers(d: dict) -> None:
    """The narration spells these values in words; refuse to record if the evidence says otherwise."""
    m, v, q = d["market"], {x["id"]: x for x in d["verdicts"]}, d["qwen_check"]
    expected = {
        "frozen hash prefix": (d["frozen"]["sha256"][:8], "bcd4e540"),
        "push time": (d["frozen"]["push"]["pushed_at"], "2026-09-24T06:35:26Z"),
        "release": (m["release_at"], "2026-09-24T20:15:00Z"),
        "8-K": (d["clock"][3]["at"], "2026-09-24T20:17:37Z"),
        "closes": (len(m["closes"]), 269),
        "baseline": (m["baseline"], 896.48),
        "trigger": (m["trigger_pct"], 3.0),
        "peak": (round(m["max_pct"], 2), 1.17),
        "book": ((m["book"]["with_visible_levels"], m["book"]["snapshots"]), (0, 270)),
        "fees": (v["c2"]["values"], ["1,850", "1,724"]),
        "margin": (v["c3"]["addendum"]["values"][0], "-11 bps"),
        "qwen": ((q["matching"], q["runs"]), (0, 5)),
        "orders": (d["decision"]["orders"], 0),
    }
    wrong = {k: a for k, (a, b) in expected.items() if a != b}
    if wrong:
        raise SystemExit(f"narration would contradict the evidence: {wrong}")


class Recorder:
    def __init__(self, page: Page | None, clips: list[tuple[Path, float]] | None = None) -> None:
        self.page = page
        self.start = time.monotonic()
        self.cues: list[tuple[float, float, str]] = []
        self.shots: list[tuple[float, str, str]] = []
        self.lines: list[str] = []
        self.clips = clips
        self.spoken: list[tuple[float, Path]] = []

    def now(self) -> float:
        return time.monotonic() - self.start

    def beat(self, step: str, caption: str, seconds: float, action=None, *, say: str | None = None) -> None:
        if self.page is None:  # planning pass: collect the spoken lines only
            self.lines.append(say or caption)
            return
        begin = self.now()
        self.page.evaluate(CAPTION_JS, caption)
        self.shots.append((begin, step, caption))
        if self.clips is not None:
            clip, length = self.clips[len(self.spoken)]
            self.spoken.append((begin, clip))
            seconds = max(seconds, length + TAIL_SECONDS)
        if action:
            action()
        remaining = seconds - (self.now() - begin)
        if remaining > 0:
            self.page.wait_for_timeout(int(remaining * 1000))
        self.cues.append((begin, self.now(), caption))

    def next(self) -> None:
        if self.page is not None:
            self.page.click("#next")
            self.page.wait_for_timeout(500)


def _ts(seconds: float, sep: str = ",") -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def script(rec: Recorder, d: dict) -> None:
    page, q = rec.page, d["qwen_check"]
    if page is not None:
        smooth = lambda sel: lambda: page.locator(sel).first.scroll_into_view_if_needed()  # noqa: E731
    else:
        smooth = lambda sel: None  # noqa: E731

    rec.beat("1 Question", "A trader's question before Costco's Q4 report: did my view survive, and what should I do with RCOST tonight?", 8,
             say="A trader asks a question before Costco's fourth quarter report. Did my view survive? And what should I do with the Ar Cost token tonight?")
    rec.beat("1 Question", "This is a recorded run from 24 September 2026. Reverb has no way to place orders: it cannot make a trade.", 4,
             say="This is a recorded run from September twenty fourth, twenty twenty six. Ree-verb has no way to place orders. It cannot make a trade.")
    rec.next()
    rec.beat("2 Claims", "The plain-words view becomes four separate claims, each with a fixed, mechanical test.", 7,
             say="The plain words view becomes four separate claims, each with a fixed, mechanical test.")
    rec.beat("2 Claims", "Qwen recorded these claims after the event; when the thesis was frozen it was unavailable, so the frozen claims are human-approved.", 7,
             smooth(".label"),
             say="The A I model recorded these claims after the event. When the thesis was frozen, it was unavailable, so the frozen claims are human approved.")
    rec.next()
    rec.beat("3 Freeze", "Your browser checks the hash again, bcd4e540…, and it matches the file pushed at 06:35 UTC, about 13h40m before the release.", 8,
             say="Your browser checks the hash again, and it matches the file pushed at six thirty five U T C, about thirteen hours and forty minutes before the release.")

    def edit() -> None:
        box = page.locator("#edits input").nth(3)
        box.click()
        box.press("End")
        for _ in range(len("margin pressure")):
            box.press("Backspace")
            page.wait_for_timeout(40)
        box.type("nothing", delay=90)

    rec.beat("3 Freeze", "Now try to edit a claim after the fact…", 5, edit if page else None,
             say="Now, try to edit a claim after the fact.")
    rec.beat("3 Freeze", "…and the hash breaks. The view can't be rewritten after the result.", 6,
             say="And the hash breaks. The view cannot be rewritten after the result.")
    rec.beat("3 Freeze", "Restore the frozen text, and the hash matches again.", 4, (lambda: page.click("#reset")) if page else None,
             say="Restore the frozen text, and the hash matches again.")
    rec.next()
    rec.beat("4 Event & market", "Event clock (UTC): frozen 06:30, pushed 06:35, Costco published results 20:15, official SEC filing 20:17.", 7,
             say="The event clock, in U T C. Frozen at six thirty. Pushed at six thirty five. Costco published its results at eight fifteen in the evening, and the official filing with regulators followed at eight seventeen.")
    rec.beat("4 Event & market", "269 recorded one-minute RCOST closes. Baseline $896.48, with a 3% trigger line on either side.", 7, smooth("svg.chart"),
             say="Two hundred sixty nine recorded one minute closes for the Ar Cost token. The baseline is eight hundred ninety six dollars and forty eight cents, with a three percent trigger line on either side.")
    rec.beat("4 Event & market", "Peak +1.17% in the release minute, under the 3% trigger. 0 of 270 minutes showed a single buy or sell order on the book.", 8, smooth(".grid2"),
             say="The peak was plus one point one seven percent, in the release minute, well under the three percent trigger. Not one of the two hundred seventy minutes showed a single buy or sell order on the book.")
    rec.next()
    rec.beat("5 Evidence", "Membership fees: Costco's own Exhibit 99.1 reports $1,850M vs $1,724M a year earlier, highlighted at its exact position.", 9,
             smooth("#hit"),
             say="Membership fees. Costco's own exhibit ninety nine point one reports one thousand eight hundred fifty million dollars, against one thousand seven hundred twenty four million a year earlier, highlighted at its exact position in the filing.")
    rec.beat("5 Evidence", "On margins, the frozen rules could not score this claim; it is confirmed only by a disclosed addendum (Costco states −11 bps).", 9,
             (lambda: (page.click("#cl button[data-id=c3]"), page.wait_for_timeout(300), page.locator("#hit").scroll_into_view_if_needed())) if page else None,
             say="On margins, the frozen rules could not score this claim. It is confirmed only by a disclosed addendum, where Costco states minus eleven basis points.")
    rec.beat("5 Evidence", "EPS: no fair benchmark was frozen, so it stays ungraded instead of being guessed.", 6,
             (lambda: (page.locator("#cl").scroll_into_view_if_needed(), page.click("#cl button[data-id=c1]"))) if page else None,
             say="E P S. No fair benchmark was frozen, so it stays ungraded, instead of being guessed.")
    rec.beat("5 Evidence", "Turning to freight: Costco never blamed freight for its margin, so that part of the view failed.", 6,
             (lambda: page.click("#cl button[data-id=c4]")) if page else None,
             say="Turning to freight costs. The company never blamed freight for its margin, so that part of the view failed.")
    rec.next()
    rec.beat("6 Verdicts", "The verdict for each claim, with the frozen rules and the disclosed addendum kept apart.", 6,
             say="The verdict for each claim, with the frozen rules and the disclosed addendum kept apart.")
    rec.beat("6 Verdicts", f"Model cross-check, measured: {q['matching']} of {q['runs']} Qwen runs agreed with the human selection. Scores come only from human-selected facts.", 9,
             smooth("h2"),
             say="The model cross check, measured. None of the five A I model runs agreed with the human selection. Scores come only from human selected facts.")
    rec.next()
    rec.beat("7 Insight", "What this means: fees confirmed, margin only by addendum, freight failed, EPS ungraded.", 8,
             say="What this means. Membership fees, confirmed. Margins, only by addendum. Freight, failed. E P S, ungraded.")
    rec.beat("7 Insight", f"HOLD, {d['decision']['orders']} orders: the move never crossed the trigger. This is not a claim that the strategy is profitable.", 8,
             smooth(".big"),
             say="Hold, with zero orders. The move never crossed the trigger. This is not a claim that the strategy is profitable.")
    rec.next()
    rec.beat("8 You decide", "Reverb recommends. The human decides.", 5,
             say="Ree-verb recommends. The human decides.")
    rec.beat("8 You decide", "Mark reviewed is stored only in this browser. Every number traces to a committed evidence file.", 6,
             (lambda: page.click("#rev")) if page else None,
             say="Mark reviewed is stored only in this browser. Every number traces to a committed evidence file.")


def check_stz_spoken_numbers(d: dict) -> None:
    """Same guard for the STZ narration: every spoken value must match the committed evidence."""
    m, v, q = d["market"], {x["id"]: x for x in d["verdicts"]}, d["qwen_check"]
    expected = {
        "frozen hash prefix": (d["frozen"]["sha256"][:8], "27abf0f7"),
        "push time": (d["frozen"]["push"]["pushed_at"], "2026-10-04T17:41:49Z"),
        "release": (m["release_at"], "2026-10-06T20:05:00Z"),
        "8-K": (next(c["at"] for c in d["clock"] if c["label"] == "SEC 8-K accepted"), "2026-10-06T20:18:54Z"),
        "second release": (next(c["at"] for c in d["clock"] if c["label"].startswith("Second")), "2026-10-06T20:15:00Z"),
        "closes": (len(m["closes"]), 239),
        "baseline": (m["baseline"], 115.67),
        "trigger": (m["trigger_pct"], 3.0),
        "low": ((round(m["mark"]["pct"], 2), m["mark"]["at"]), (-5.31, "2026-10-06T20:26:00Z")),
        "first crossing": (m["first_crossing"][0], "2026-10-06T20:23:00Z"),
        "book": ((m["book"]["with_visible_levels"], m["book"]["snapshots"]), (0, 270)),
        "sales": (v["c1"]["values"], ["$2,473.6", "$2,345.0"]),
        "depletions": (v["c2"]["values"][0], "(0.6%)"),
        "margin": (v["c3"]["values"], ["39.0%", "40.6%"]),
        "statuses": ([v[c]["frozen_status"] for c in ("c1", "c2", "c3", "c4")],
                     ["CONFIRMED", "CONTRADICTED", "CONFIRMED", "NOT_ADDRESSED"]),
        "qwen": ((q["schema_valid"], q["runs"], q["per_claim"]), (4, 5, {"c2": 3, "c3": 3})),
        "decision": ((d["decision"]["action"], d["decision"]["orders"]), ("REVIEW", 0)),
    }
    wrong = {k: a for k, (a, b) in expected.items() if a != b}
    if wrong:
        raise SystemExit(f"narration would contradict the evidence: {wrong}")


# Lift the referenced element above the caption box (bottom ~200px of the frame).
LIFT_JS = """sel => { const el = document.querySelector(sel); if (!el) return;
  const r = el.getBoundingClientRect(), limit = innerHeight - 200;
  if (r.bottom > limit) window.scrollBy(0, Math.min(r.top - 80, r.bottom - limit)); }"""


def stz_script(rec: Recorder, d: dict) -> None:
    page = rec.page
    if page is not None:
        page.add_style_tag(content="body{padding-bottom:260px}")
        smooth = lambda sel: lambda: page.evaluate(LIFT_JS, sel)  # noqa: E731
        claim = lambda cid: lambda: (page.click(f'#cl button[data-id="{cid}"]'), page.wait_for_timeout(300),  # noqa: E731
                                     page.evaluate(LIFT_JS, ".doc"))
    else:
        smooth = claim = lambda _: None  # noqa: E731

    rec.beat("1 Question", "Reverb's second forward run: Constellation Brands' Q2 report. Did the view survive, and what should I do with RSTZ tonight?", 8,
             say="This is Ree-verb's second forward run: Constellation Brands' second quarter report. Did the view survive? And what should I do with the Ar S T Z token tonight?")
    rec.beat("1 Question", "A recorded run from 6 October 2026. Reverb has no way to place orders: it cannot make a trade.", 4,
             say="This is a recorded run from October sixth, twenty twenty six. Ree-verb has no way to place orders. It cannot make a trade.")
    rec.next()
    rec.beat("2 Claims", "The view becomes four claims, each with a fixed, mechanical test.", 6,
             say="The view becomes four separate claims, each with a fixed, mechanical test.")
    rec.beat("2 Claims", "I built this view from Constellation's own earlier filings and approved it before the report.", 6,
             smooth(".label"),
             say="I built this view from Constellation's own earlier filings, and approved it before the report.")
    rec.next()
    rec.beat("3 Freeze", "Your browser checks the hash again, 27abf0f7…, and it matches the file pushed on 4 October, two days before the release.", 8,
             smooth("#hashnote"),
             say="Your browser checks the hash again, and it matches the file pushed on October fourth, two days before the release.")

    def edit() -> None:
        box = page.locator("#edits input").nth(3)
        box.click()
        box.press("End")
        for _ in range(len("beer margin")):
            box.press("Backspace")
            page.wait_for_timeout(40)
        box.type("nothing", delay=90)

    rec.beat("3 Freeze", "Now try to edit a claim after the fact…", 5, edit if page else None,
             say="Now, try to edit a claim after the fact.")
    rec.beat("3 Freeze", "…and the hash breaks. The view can't be rewritten after the result.", 6, smooth("#hashnote"),
             say="And the hash breaks. The view cannot be rewritten after the result.")
    rec.beat("3 Freeze", "Restore the frozen text, and the hash matches again.", 4,
             (lambda: (page.click("#reset"), page.wait_for_timeout(300), page.evaluate(LIFT_JS, "#hashnote"))) if page else None,
             say="Restore the frozen text, and the hash matches again.")
    rec.next()
    rec.beat("4 Event & market", "Event clock (ET): Constellation published results at 16:05, a second release at 16:15, the SEC filing at 16:18.", 8,
             say="The event clock. Constellation published results at four oh five p m Eastern, a second release, an acquisition, at four fifteen, and the S E C filing at four eighteen.")
    rec.beat("4 Event & market", "239 recorded one-minute RSTZ closes. Baseline $115.67, with a 3% trigger line on either side.", 7, smooth("svg.chart"),
             say="Two hundred thirty nine recorded one minute closes. The baseline is one hundred fifteen dollars sixty seven, with a three percent trigger line on either side.")
    rec.beat("4 Event & market", "It crossed −3% at 16:23 ET and hit a low of −5.31% at 16:26. 0 of 270 minutes showed a single order on the book.", 9, smooth(".grid2"),
             say="The price crossed minus three percent at four twenty three, and fell to minus five point three one percent at four twenty six. Not one of the two hundred seventy minutes showed a single order on the public book.")
    rec.next()
    rec.beat("5 Evidence", "Beer net sales: Constellation's own Exhibit 99.1 reports $2,473.6M vs $2,345.0M, highlighted at its exact position.", 9,
             claim("c1") if page else None,
             say="First, beer net sales. Constellation's own exhibit ninety nine point one reports two thousand four hundred seventy three million, against two thousand three hundred forty five million a year earlier. That claim is confirmed.")
    rec.beat("5 Evidence", "Depletions: the same table shows (0.6%), a decline. That claim is contradicted.", 7, claim("c2") if page else None,
             say="Second, depletions. The same table shows a decline of zero point six percent. That claim is contradicted.")
    rec.beat("5 Evidence", "Beer margin: 39.0%, below last year's frozen 40.6%. Confirmed.", 6, claim("c3") if page else None,
             say="As for the third claim, beer operating margin was thirty nine percent, below last year's frozen forty point six. That claim is confirmed too.")
    rec.beat("5 Evidence", "The reason: Constellation called lower tariffs a help and blamed marketing and SG&A. The tariff story wasn't theirs.", 8,
             claim("c4") if page else None,
             say="As for the reason behind the view, Constellation said lower tariffs helped, and blamed marketing and other spending. The tariff story was not theirs.")
    rec.next()
    rec.beat("6 Verdicts", "Two of three scored claims confirmed. Depletions failed; the tariff reason was not addressed.", 7,
             say="Two of three scored claims were confirmed. Depletions failed, and the tariff reason was not addressed.")
    rec.beat("6 Verdicts", "Model cross-check: 4 of 5 Qwen runs valid; it matched depletions and margin 3 times, never sales. Scores come only from human-selected facts.", 10,
             smooth("h2"),
             say="The model cross check, measured. Four of five A I model runs returned valid output. It matched depletions and margin three times, and never matched sales. Scores come only from human selected facts.")
    rec.next()
    rec.beat("7 Insight", "Right on the numbers, wrong on the reason, and depletions missed.", 6,
             say="So: right on the numbers, wrong on the reason, and depletions missed.")
    rec.beat("7 Insight", "REVIEW, 0 orders: the move crossed the trigger, but an acquisition landed in the same window and there was no depth to trade.", 10,
             smooth(".big"),
             say="The move crossed the trigger, so the rule says review, with zero orders. An acquisition landed in the same window, and there was no order book depth to trade into. This is not a claim that the strategy is profitable.")
    rec.next()
    rec.beat("8 You decide", "Reverb recommends. The human decides.", 5,
             say="Ree-verb recommends. The human decides.")
    rec.beat("8 You decide", "Every number traces to a committed evidence file. Next up: Applied Digital, recording tonight.", 6,
             say="Every number traces to a committed evidence file. Next up is the Applied Digital report, recording tonight.")


def check_apld_spoken_numbers(d: dict) -> None:
    """Same guard for the APLD narration: every spoken value must match the committed evidence."""
    m, v, q = d["market"], {x["id"]: x for x in d["verdicts"]}, d["qwen_check"]
    expected = {
        "frozen hash prefix": (d["frozen"]["sha256"][:8], "3f707686"),
        "push time": (d["frozen"]["push"]["pushed_at"], "2026-10-04T17:42:05Z"),
        "release": (m["release_at"], "2026-10-07T20:27:00Z"),
        "8-K": (next(c["at"] for c in d["clock"] if c["label"] == "SEC 8-K accepted"), "2026-10-07T20:43:31Z"),
        "closes": (len(m["closes"]), 269),
        "baseline": (m["baseline"], 23.81),
        "trigger": (m["trigger_pct"], 3.0),
        "peak": ((round(m["mark"]["pct"], 2), m["mark"]["at"]), (4.75, "2026-10-07T20:27:00Z")),
        "held from": (m["held_from"], "2026-10-07T21:32:00Z"),
        "last": (round(m["last_pct"], 2), 4.49),
        "book": ((m["book"]["with_visible_levels"], m["book"]["snapshots"]), (270, 270)),
        "revenue": (v["c1"]["values"], ["$341.9 million", "$258.7 million"]),
        "ebitda": (v["c2"]["values"], ["$64.4 million", "$42.4 million"]),
        "net loss": (v["c3"]["values"], ["$221.0 million", "$110.6 million"]),
        "capacity": ((v["c4"]["evidence"]["match"].count("1.41 GW"), v["c4"]["reference"]), (1, "1,410")),
        "statuses": ([v[c]["frozen_status"] for c in ("c1", "c2", "c3", "c4")],
                     ["CONFIRMED", "CONFIRMED", "CONTRADICTED", "NOT_ADDRESSED"]),
        "qwen": ((q["schema_valid"], q["runs"], q["matched_every_claim"], q["per_claim"]), (4, 5, 0, {"c2": 3})),
        "decision": ((d["decision"]["action"], d["decision"]["orders"]), ("REVIEW", 0)),
    }
    wrong = {k: a for k, (a, b) in expected.items() if a != b}
    if wrong:
        raise SystemExit(f"narration would contradict the evidence: {wrong}")


def apld_script(rec: Recorder, d: dict) -> None:
    page = rec.page
    if page is not None:
        page.add_style_tag(content="body{padding-bottom:260px}")
        smooth = lambda sel: lambda: page.evaluate(LIFT_JS, sel)  # noqa: E731
        claim = lambda cid: lambda: (page.click(f'#cl button[data-id="{cid}"]'), page.wait_for_timeout(300),  # noqa: E731
                                     page.evaluate(LIFT_JS, ".doc"))
    else:
        smooth = claim = lambda _: None  # noqa: E731

    rec.beat("1 Question", "Reverb's third forward run: Applied Digital's Q1 report. Did the view survive, and what should I do with RAPLD tonight?", 8,
             say="This is Ree-verb's third forward run: Applied Digital's first quarter report. Did the view survive? And what should I do with the Ar A P L D token tonight?")
    rec.beat("1 Question", "A recorded run from 7 October 2026. Reverb has no way to place orders: it cannot make a trade.", 4,
             say="This is a recorded run from October seventh, twenty twenty six. Ree-verb has no way to place orders. It cannot make a trade.")
    rec.next()
    rec.beat("2 Claims", "The view becomes four claims, each with a fixed, mechanical test against last quarter's numbers.", 6,
             say="The view becomes four separate claims, each with a fixed, mechanical test against last quarter's numbers.")
    rec.beat("2 Claims", "I built this view from Applied Digital's own earlier filings and approved it before the report.", 6,
             smooth(".label"),
             say="I built this view from Applied Digital's own earlier filings, and approved it before the report.")
    rec.next()
    rec.beat("3 Freeze", "Your browser checks the hash again, 3f707686…, and it matches the file pushed on 4 October, three days before the release.", 8,
             smooth("#hashnote"),
             say="Your browser checks the hash again, and it matches the file pushed on October fourth, three days before the release.")

    def edit() -> None:
        box = page.locator("#edits input").nth(3)
        box.click()
        box.press("End")
        for _ in range(len("1,410 MW")):
            box.press("Backspace")
            page.wait_for_timeout(40)
        box.type("500 MW", delay=90)

    rec.beat("3 Freeze", "Now try to edit a claim after the fact…", 5, edit if page else None,
             say="Now, try to edit a claim after the fact.")
    rec.beat("3 Freeze", "…and the hash breaks. The view can't be rewritten after the result.", 6, smooth("#hashnote"),
             say="And the hash breaks. The view cannot be rewritten after the result.")
    rec.beat("3 Freeze", "Restore the frozen text, and the hash matches again.", 4,
             (lambda: (page.click("#reset"), page.wait_for_timeout(300), page.evaluate(LIFT_JS, "#hashnote"))) if page else None,
             say="Restore the frozen text, and the hash matches again.")
    rec.next()
    rec.beat("4 Event & market", "Event clock (ET): Applied Digital published results at 16:27; the SEC filing followed at 16:43.", 7,
             say="The event clock. Applied Digital published results at four twenty seven p m Eastern, and the S E C filing followed at four forty three.")
    rec.beat("4 Event & market", "269 recorded one-minute RAPLD closes. Baseline $23.81, with a 3% trigger line on either side.", 7, smooth("svg.chart"),
             say="Two hundred sixty nine recorded one minute closes. The baseline is twenty three dollars eighty one, with a three percent trigger line on either side.")
    rec.beat("4 Event & market", "A one-minute spike to +4.75% at the release, then straight back. It held above +3% from 17:32 ET and ended +4.49%. All 270 minutes had book depth.", 11,
             smooth(".grid2"),
             say="In the release minute the price spiked to plus four point seven five percent, then fell straight back. It held above plus three percent from five thirty two, and ended the window up four point four nine percent. Every one of the two hundred seventy minutes had visible depth on the public book.")
    rec.next()
    rec.beat("5 Evidence", "Revenue: Applied Digital's own Exhibit 99.1 reports $341.9M, above last quarter's frozen $258.7M. Confirmed.", 9,
             claim("c1") if page else None,
             say="First, revenue. Applied Digital's own exhibit ninety nine point one reports three hundred forty one point nine million, above last quarter's frozen two hundred fifty eight point seven million. That claim is confirmed.")
    rec.beat("5 Evidence", "Adjusted EBITDA: $64.4M, above the frozen $42.4M. Confirmed.", 6, claim("c2") if page else None,
             say="Second, adjusted EBITDA: sixty four point four million, above the frozen forty two point four. That claim is confirmed as well.")
    rec.beat("5 Evidence", "Net loss: $221.0M. It widened from $110.6M instead of narrowing. Contradicted.", 7, claim("c3") if page else None,
             say="Third, the net loss. It was two hundred twenty one million. It widened from one hundred ten point six million, instead of narrowing. That claim is contradicted.")
    rec.beat("5 Evidence", "New lease: the release states 1.41 GW, the same as the frozen 1,410 MW, and names no new lease. The unit differs, so it is not scored.", 9,
             claim("c4") if page else None,
             say="Last, the new lease. The release states one point four one gigawatts, the same as the frozen one thousand four hundred ten megawatts, and names no new lease. Because the unit differs, it is not scored.")
    rec.next()
    rec.beat("6 Verdicts", "Two of three scored claims confirmed. The net loss widened; the lease claim was not scored.", 7,
             say="Two of three scored claims were confirmed. The net loss widened, and the lease claim was not scored.")
    rec.beat("6 Verdicts", "Out-of-sample model check: 4 of 5 Qwen runs valid, none matched every claim; only adjusted EBITDA matched, 3 times. Scores come only from hand-selected facts.", 10,
             smooth("h2"),
             say="The model cross check, on a report it had never seen. Four of five A I model runs returned valid output, but none matched every claim. Only adjusted EBITDA matched, three times. Scores come only from hand selected facts.")
    rec.next()
    rec.beat("7 Insight", "Right on growth, wrong on losses, and no new lease.", 6,
             say="So: right on growth, wrong on losses, and no new lease.")
    rec.beat("7 Insight", "REVIEW, 0 orders: the move crossed the trigger and this time the book had depth, but the run was registered read-only.", 10,
             smooth(".big"),
             say="The move crossed the trigger, so the rule says review, with zero orders. This time the book had depth to trade into, but the run was registered read only. This is not a claim that the strategy is profitable.")
    rec.next()
    rec.beat("8 You decide", "Reverb recommends. The human decides.", 5,
             say="Ree-verb recommends. The human decides.")
    rec.beat("8 You decide", "Three forward runs: Costco, Constellation and Applied Digital. Every number traces to a committed evidence file.", 7,
             say="That is three forward runs: Costco, Constellation, and Applied Digital. Every number traces to a committed evidence file.")


def synthesise(lines: list[str], voice: Path, directory: Path) -> list[tuple[Path, float]]:
    directory.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, line in enumerate(lines, 1):
        path = directory / f"{i:02d}.wav"
        subprocess.run([sys.executable, "-m", "piper", "-m", str(voice), "-f", str(path), "--length-scale", "1.05",
                        "--sentence-silence", "0.3"], input=line, text=True, check=True, capture_output=True)
        length = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                       str(path)], capture_output=True, text=True, check=True).stdout)
        clips.append((path, length))
    return clips


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, default=ROOT / "data/private/recordings")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--voice", type=Path, help="Piper .onnx voice; adds a narration track")
    parser.add_argument("--smoke", action="store_true", help="record a 10-second clip only")
    parser.add_argument("--event", choices=("costco", "stz", "apld"), default="costco")
    args = parser.parse_args()
    events = {"costco": (NAME, script, DEFAULT_URL, walkthrough_data, check_spoken_numbers),
              "stz": (STZ_NAME, stz_script, STZ_URL, stz_walkthrough_data, check_stz_spoken_numbers),
              "apld": (APLD_NAME, apld_script, APLD_URL, apld_walkthrough_data, check_apld_spoken_numbers)}
    name_root, run_script, event_url, load_data, check_numbers = events[args.event]
    if args.url == DEFAULT_URL:
        args.url = event_url
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")
    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / "_video"
    shutil.rmtree(tmp, ignore_errors=True)
    data = load_data()
    check_numbers(data)
    clips = None
    if args.voice and not args.smoke:
        planner = Recorder(None)
        run_script(planner, data)
        clips = synthesise(planner.lines, args.voice, tmp / "voice")
        (args.out / f"{name_root}-narration.txt").write_text("\n".join(planner.lines) + "\n", encoding="utf-8")
    size = {"width": args.width, "height": args.height}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=size, record_video_dir=str(tmp), record_video_size=size,
                                      device_scale_factor=1, color_scheme="light", timezone_id="UTC")
        video_start = time.monotonic()
        page = context.new_page()
        page.goto(args.url + "#1", wait_until="networkidle")
        page.add_style_tag(content="main,header{max-width:1200px}body{font-size:18px;padding-bottom:110px}")
        rec = Recorder(page, clips)
        if args.smoke:
            rec.beat("smoke", "Smoke test: recording works.", 10)
        else:
            run_script(rec, data)
        lead = rec.start - video_start  # captions are timed from when the page was ready, the video from page creation
        context.close()
        browser.close()
    webm = next(tmp.glob("*.webm"))
    name = f"{name_root}-smoke" if args.smoke else name_root
    mp4 = args.out / f"{name}.mp4"
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm)]
    if clips:
        for _, clip in rec.spoken:
            command += ["-i", str(clip)]
        delays = "".join(f"[{i}:a]adelay={int((begin + lead) * 1000)}:all=1[a{i}];"
                         for i, (begin, _) in enumerate(rec.spoken, 1))
        mix = "".join(f"[a{i}]" for i in range(1, len(rec.spoken) + 1))
        command += ["-filter_complex", f"{delays}{mix}amix=inputs={len(rec.spoken)}:normalize=0,loudnorm=I=-16:TP=-1.5[aout]",
                    "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "128k", "-ar", "48000"]
    else:
        command += ["-an"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-threads", "1", "-crf", "22",
                "-movflags", "+faststart", str(mp4)]
    subprocess.run(command, check=True)
    shutil.rmtree(tmp)
    (args.out / f"{name}.srt").write_text("".join(
        f"{i}\n{_ts(a + lead)} --> {_ts(b + lead)}\n{text}\n\n" for i, (a, b, text) in enumerate(rec.cues, 1)), encoding="utf-8")
    shots = ["| Time | Step | Caption |", "|---|---|---|",
             *[f"| {_ts(t + lead, '.')[3:8]} | {step} | {text} |" for t, step, text in rec.shots]]
    (args.out / f"{name}-shots.md").write_text(f"# Shot list: {name}\n\nRecorded from {args.url}\n\n" + "\n".join(shots) + "\n", encoding="utf-8")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
                            "-of", "json", str(mp4)], capture_output=True, text=True, check=True)
    print(json.dumps({"mp4": str(mp4), "probe": json.loads(probe.stdout)}, indent=1))


if __name__ == "__main__":
    main()
