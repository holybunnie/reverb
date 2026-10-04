"""Screen-record the deployed research-task walkthrough with on-screen captions.

Drives headless Chromium through all eight steps at a readable pace, overlays one
caption per beat, and writes an MP4, an .srt caption file, and a timestamped shot
list. Needs Playwright (with Chromium) and ffmpeg in a scratch environment; neither
is a project dependency.

    python scripts/record_walkthrough.py [--url URL] [--out data/private/recordings]
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

DEFAULT_URL = "https://holybunnie.github.io/reverb/walkthrough/"
NAME = "research-task-costco"

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


class Recorder:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.start = time.monotonic()
        self.cues: list[tuple[float, float, str]] = []
        self.shots: list[tuple[float, str, str]] = []

    def now(self) -> float:
        return time.monotonic() - self.start

    def beat(self, step: str, caption: str, seconds: float, action=None) -> None:
        begin = self.now()
        self.page.evaluate(CAPTION_JS, caption)
        self.shots.append((begin, step, caption))
        if action:
            action()
        remaining = seconds - (self.now() - begin)
        if remaining > 0:
            self.page.wait_for_timeout(int(remaining * 1000))
        self.cues.append((begin, self.now(), caption))

    def next(self) -> None:
        self.page.click("#next")
        self.page.wait_for_timeout(500)


def _ts(seconds: float, sep: str = ",") -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def script(rec: Recorder, d: dict) -> None:
    page, m = rec.page, d["market"]
    head = d["frozen"]["sha256"][:8]
    v = {x["id"]: x for x in d["verdicts"]}
    smooth = lambda sel: lambda: page.locator(sel).first.scroll_into_view_if_needed()  # noqa: E731

    rec.beat("1 Question", "A trader's question before Costco's Q4 report: did my view survive, and what should I do with RCOST?", 8)
    rec.beat("1 Question", "Recorded run from 24 Sep 2026. Reverb has no order path: live_orders_allowed is false.", 4)
    rec.next()
    rec.beat("2 Claims", "The plain-words view becomes four claims, each with a deterministic test.", 7)
    rec.beat("2 Claims", f"Claims recorded from {d['qwen_recorded']['model']} after the event; the freeze-time call was unavailable, so the frozen claims are human-approved.", 7,
             smooth(".label"))
    rec.next()
    rec.beat("3 Freeze", f"Hash recomputed in your browser: {head}… matches the frozen file pushed {d['frozen']['push']['pushed_at'][11:16]} UTC, about 13h40m before the release.", 8)

    def edit() -> None:
        box = page.locator("#edits input").nth(3)
        box.click()
        box.press("End")
        for _ in range(len("margin pressure")):
            box.press("Backspace")
            page.wait_for_timeout(40)
        box.type("nothing", delay=90)

    rec.beat("3 Freeze", "Now rewrite a claim after the fact…", 5, edit)
    rec.beat("3 Freeze", "…and the hash breaks. The view can't be rewritten after the result.", 6)
    rec.beat("3 Freeze", "Restore the frozen text: the hash matches again.", 4, lambda: page.click("#reset"))
    rec.next()
    rec.beat("4 Event & market", "Event clock: frozen 06:30 UTC, pushed 06:35, Costco released 20:15, SEC 8-K accepted 20:17:37.", 7)
    rec.beat("4 Event & market", f"{len(m['closes'])} recorded one-minute RCOST closes. Baseline ${m['baseline']}, ±{m['trigger_pct']}% trigger band.", 7, smooth("svg.chart"))
    rec.beat("4 Event & market", f"Peak {m['max_pct']:+.2f}% in the release minute, under the {m['trigger_pct']}% trigger. "
                                 f"{m['book']['with_visible_levels']} of {m['book']['snapshots']} minutes had any visible book depth.", 8, smooth(".grid2"))
    rec.next()
    rec.beat("5 Evidence", f"Membership fees: Costco's own Exhibit 99.1 line, {v['c2']['values'][0]} vs {v['c2']['values'][1]}, highlighted at its exact offsets.", 9,
             smooth("#hit"))
    rec.beat("5 Evidence", f"Margins: unscored by the frozen rules; confirmed only by a disclosed addendum ({v['c3']['addendum']['values'][0]}, Exhibit 99.2).", 9,
             lambda: (page.click("#cl button[data-id=c3]"), page.wait_for_timeout(300), page.locator("#hit").scroll_into_view_if_needed()))
    rec.beat("5 Evidence", "EPS: no fair benchmark was frozen, so it stays ungraded instead of guessed.", 6,
             lambda: (page.locator("#cl").scroll_into_view_if_needed(), page.click("#cl button[data-id=c1]")))
    rec.beat("5 Evidence", "Freight: Costco never attributed margin to freight, so that part of the view failed.", 6,
             lambda: page.click("#cl button[data-id=c4]"))
    rec.next()
    q = d["qwen_check"]
    rec.beat("6 Verdicts", "Verdict per claim, frozen rules and disclosed addendum kept apart.", 6)
    rec.beat("6 Verdicts", f"Model cross-check, measured: {q['matching']} of {q['runs']} {q['model']} runs matched the human selection. Scores come from the human-selected facts.", 9,
             smooth("h2"))
    rec.next()
    rec.beat("7 Insight", "Actionable insight: fees confirmed, margin only by addendum, freight failed, EPS ungraded.", 8)
    rec.beat("7 Insight", f"HOLD, {d['decision']['orders']} orders: the move never crossed the trigger. Not a claim that the strategy is profitable.", 8, smooth(".big"))
    rec.next()
    rec.beat("8 You decide", "Reverb recommends. The human decides.", 5)
    rec.beat("8 You decide", "Mark reviewed is stored only in this browser. Every number traces to a committed evidence file.", 6,
             lambda: page.click("#rev"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, default=ROOT / "data/private/recordings")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--smoke", action="store_true", help="record a 10-second clip only")
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")
    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / "_video"
    shutil.rmtree(tmp, ignore_errors=True)
    data = walkthrough_data()
    size = {"width": args.width, "height": args.height}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=size, record_video_dir=str(tmp), record_video_size=size,
                                      device_scale_factor=1, color_scheme="light", timezone_id="UTC")
        video_start = time.monotonic()
        page = context.new_page()
        page.goto(args.url + "#1", wait_until="networkidle")
        page.add_style_tag(content="main,header{max-width:1200px}body{font-size:18px;padding-bottom:110px}")
        rec = Recorder(page)
        if args.smoke:
            rec.beat("smoke", "Smoke test: recording works.", 10)
        else:
            script(rec, data)
        lead = rec.start - video_start  # captions are timed from when the page was ready, the video from page creation
        context.close()
        browser.close()
    webm = next(tmp.glob("*.webm"))
    name = f"{NAME}-smoke" if args.smoke else NAME
    mp4 = args.out / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "veryfast", "-threads", "1", "-crf", "22", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    shutil.rmtree(tmp)
    (args.out / f"{name}.srt").write_text("".join(
        f"{i}\n{_ts(a + lead)} --> {_ts(b + lead)}\n{text}\n\n" for i, (a, b, text) in enumerate(rec.cues, 1)), encoding="utf-8")
    shots = ["| Time | Step | Caption |", "|---|---|---|",
             *[f"| {_ts(t + lead, '.')[3:8]} | {step} | {text} |" for t, step, text in rec.shots]]
    (args.out / f"{name}-shots.md").write_text(f"# Shot list: {name}\n\nRecorded from {args.url}\n\n" + "\n".join(shots) + "\n", encoding="utf-8")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_name",
                            "-of", "json", str(mp4)], capture_output=True, text=True, check=True)
    print(json.dumps({"mp4": str(mp4), "probe": json.loads(probe.stdout)}, indent=1))


if __name__ == "__main__":
    main()
