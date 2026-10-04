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

DEFAULT_URL = "https://holybunnie.github.io/reverb/walkthrough/"
NAME = "research-task-costco"
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
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")
    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / "_video"
    shutil.rmtree(tmp, ignore_errors=True)
    data = walkthrough_data()
    check_spoken_numbers(data)
    clips = None
    if args.voice and not args.smoke:
        planner = Recorder(None)
        script(planner, data)
        clips = synthesise(planner.lines, args.voice, tmp / "voice")
        (args.out / f"{NAME}-narration.txt").write_text("\n".join(planner.lines) + "\n", encoding="utf-8")
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
            script(rec, data)
        lead = rec.start - video_start  # captions are timed from when the page was ready, the video from page creation
        context.close()
        browser.close()
    webm = next(tmp.glob("*.webm"))
    name = f"{NAME}-smoke" if args.smoke else NAME
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
