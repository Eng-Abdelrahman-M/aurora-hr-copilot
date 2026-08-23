"""Drive the demo in a visible browser so you can narrate over it.

Moves like a person: hovers before clicking, types character by character with
uneven rhythm, pauses to "read" each answer, then expands the agent-trace
panel. You just talk.

  python scripts/demo.py                     # local, http://localhost:8100
  DEMO_URL=https://<app>.onrender.com DEMO_TOKEN=<token> python scripts/demo.py

  PAUSE=10 python scripts/demo.py            # slower, more talking room
  PAUSE=0  python scripts/demo.py            # advance on Enter — best for recording
  HUMAN=0  python scripts/demo.py            # instant typing, no jitter
  HEADLESS=1 python scripts/demo.py          # no window — dry run / CI check

Setup once:  pip install -r requirements-dev.txt && playwright install chromium
"""
import os
import random
import sys
import time

from playwright.sync_api import sync_playwright

URL = os.environ.get("DEMO_URL", "http://localhost:8100")
TOKEN = os.environ.get("DEMO_TOKEN", "")
PAUSE = float(os.environ.get("PAUSE", 6))
HUMAN = os.environ.get("HUMAN", "1") == "1"
HEADLESS = os.environ.get("HEADLESS") == "1"
ANSWER_TIMEOUT = 180_000  # ms — generous: covers a free-tier cold start

# Seeded, so two takes of the demo behave identically — same repo-wide rule as
# deterministic chunking and temperature 0.
rng = random.Random(7)

# (narration cue, message, sidebar button to click instead of typing)
#
# Phrased the way someone actually types — nobody opens with "I'm EMP003".
# The agent asks for the ID when it needs one, which is the missing-ID
# guardrail doing its job on camera rather than a rehearsed line.
STEPS = [
    ("TASK 1 — PTO request. Asked the way a person actually asks.",
     "Hi, I'm Abdelrahman Othman. Can I take 3 days off the week of "
     "September 21? I'd like to get it requested if I'm able to.", None),

    ("It did NOT file a ticket — it proposed one and stopped. Now I confirm.",
     "yes, please create it", None),

    ("TASK 2 — Remote work abroad. Multi-document, and country != state.",
     "Different question — I want to work from Portugal for six weeks this "
     "fall. Does my role and work setup allow that, and what do I need to do?",
     None),

    ("Draft goes THROUGH the draft_hr_email tool, so it lands in the trace.",
     "can you draft the email to my manager?", None),

    ("Out of corpus — it declines instead of guessing, and cites nothing.",
     "what's the capital gains tax rate on my RSUs?", None),
]


def beat(lo, hi):
    """A short human hesitation. No-op when HUMAN=0."""
    if HUMAN and not HEADLESS:
        time.sleep(rng.uniform(lo, hi))


def send_message(page, message, button_label):
    """Click the sidebar task button if there is one, else type it out."""
    if button_label:
        btn = page.locator("button.task", has_text=button_label).first
        btn.hover()                      # cursor travels before it clicks
        beat(0.3, 0.7)
        btn.click()
        return

    box = page.locator("#q")
    box.hover()
    beat(0.2, 0.5)
    box.click()
    beat(0.3, 0.8)                       # a moment of thought before typing
    if HUMAN and not HEADLESS:
        # press_sequentially fires real key events; the uneven per-character
        # delay is what keeps it from looking like a paste.
        for chunk in message.split(" "):
            box.press_sequentially(chunk + " ", delay=rng.uniform(38, 85))
            if rng.random() < 0.12:
                time.sleep(rng.uniform(0.15, 0.4))   # mid-sentence pause
    else:
        box.fill(message)
    beat(0.3, 0.6)
    page.locator("#send").hover()
    page.locator("#send").click()


def wait_for_answer(page):
    """The UI disables #send while a turn is in flight.

    The token-unlock turn never reaches the LLM, so it can finish before we
    observe the disabled state — missing that is fine, not an error. The UI
    re-enables #send only after the reply is rendered, so the second wait is
    still a correct completion signal on its own.
    """
    try:
        page.wait_for_selector("#send[disabled]", timeout=5_000)
    except Exception:
        pass
    page.wait_for_selector("#send:not([disabled])", timeout=ANSWER_TIMEOUT)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS,
                                    slow_mo=0 if HEADLESS else 40)
        page = browser.new_context(
            viewport={"width": 1440, "height": 900},
        ).new_page()

        print("\n  opening " + URL)
        page.goto(URL, timeout=ANSWER_TIMEOUT)
        page.wait_for_selector("#q")

        # Let the health pill resolve first — it is the on-screen proof that
        # MCP connected.
        page.wait_for_selector("#health .dot.ok", timeout=60_000)
        page.locator("#health").hover()
        print("  MCP connected (health pill green)\n")

        # A gated deployment asks for the token in the chat itself. Unlock it
        # before the narration starts so the recording opens on a ready app.
        if TOKEN:
            page.fill("#q", TOKEN)
            page.click("#send")
            wait_for_answer(page)
            print("  session unlocked with DEMO_TOKEN")
        pause("Point at the health pill, then start Task 1")

        for i, (cue, message, button_label) in enumerate(STEPS, 1):
            print(f"\n[{i}/{len(STEPS)}] {cue}")
            print(f"      > {message}")
            # A turn that calls no tools appends no trace panel, and a turn
            # with no citations appends no chip row — so count first and only
            # report what this turn actually added. Otherwise .last silently
            # shows the previous turn's tools, which is worse than showing
            # nothing when you are reading it aloud on camera.
            traces, cites = page.locator("details.trace"), page.locator("div.cites")
            before_traces, before_cites = traces.count(), cites.count()

            send_message(page, message, button_label)
            wait_for_answer(page)
            beat(0.6, 1.2)               # let the answer land before poking it

            if traces.count() > before_traces:
                # Expand it — collapsed by default, and it is what the rubric
                # wants on screen.
                traces.last.scroll_into_view_if_needed()
                traces.last.locator("summary").hover()
                beat(0.2, 0.5)
                traces.last.evaluate("d => d.open = true")
                traces.last.scroll_into_view_if_needed()
                tools = traces.last.locator(".tname").all_inner_texts()
                print(f"      tools called: {' -> '.join(tools)}")
            else:
                print("      tools called: none — answered without tools")

            if cites.count() > before_cites:
                print(f"      citations: {' | '.join(cites.last.locator('.cite').all_inner_texts())}")
            else:
                print("      citations: none")
            pause("Read the tool calls aloud, then continue")

        print("\n  Demo complete. Browser stays open — close it when you're done.")
        input("  Press Enter to close the browser...")
        browser.close()


def pause(hint):
    if PAUSE <= 0:
        input(f"      [{hint} — Enter to continue]")
    else:
        print(f"      [{hint} — {PAUSE:g}s]")
        time.sleep(PAUSE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n  stopped")
