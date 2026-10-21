"""LFG Dictate helper: the login agent that listens for the shortcut and puts dictated text where the cursor is.

Runs in Dictate's private environment (~/.lfg/dictate/venv: cactus-needle, sounddevice, PyObjC), started by launchd
with telemetry off and Hugging Face offline (see dictate.py). Flow: the shortcut starts the microphone and a small
"Listening" panel; when the dictation ends the audio is transcribed on-device by Whistle, optionally cleaned up by
Claude (text only, only when the user turned "Clean up" on), then pasted (clipboard restored) or typed into the focused
app. With no text field focused, the text stays on the clipboard. No audio and no transcript is written to disk.
"""
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

import AppKit
import ApplicationServices as AS
import numpy
import Quartz
import sounddevice
import soxr
from PyObjCTools import AppHelper

from lfgcore import dictate as D

RATE = 16000
MOD_FLAGS = {"alt": Quartz.kCGEventFlagMaskAlternate, "ctrl": Quartz.kCGEventFlagMaskControl,
             "cmd": Quartz.kCGEventFlagMaskCommand, "shift": Quartz.kCGEventFlagMaskShift}
MOD_FLAG_FOR_KEY = {63: Quartz.kCGEventFlagMaskSecondaryFn, 61: Quartz.kCGEventFlagMaskAlternate}
ESC = 53
CLEANUP_PROMPT = ("Clean up this dictated text. Remove filler words (um, uh, like), apply spoken corrections "
                  "(\"Tuesday, no, Wednesday\" becomes \"Wednesday\"), fix punctuation and capitalisation. Keep the "
                  "speaker's words and meaning; do not add anything. Reply with the cleaned text only.")


# ---------------------------------------------------------------- the "Listening" panel

class Indicator:
    """A small, quiet pill at the bottom centre of the screen. While listening it shows only bars that move with your
    voice (no words); while transcribing the bars dim and pulse; it shows text only when it has something to say
    ("Copied: press ⌘V", an error). It never takes focus or clicks."""
    BARS = 9
    SHAPE = (0.35, 0.55, 0.75, 0.9, 1.0, 0.9, 0.75, 0.55, 0.35)  # middle bars move most
    H, BAR_W, GAP, PAD = 26, 2.5, 3, 12

    def __init__(self, level):
        self.level = level  # callable: the microphone's current loudness, 0..1
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        p = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, 80, self.H), style, AppKit.NSBackingStoreBuffered, False)
        p.setLevel_(AppKit.NSStatusWindowLevel)
        p.setOpaque_(False)
        p.setHasShadow_(True)
        p.setBackgroundColor_(AppKit.NSColor.clearColor())
        p.setIgnoresMouseEvents_(True)
        p.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
        view = p.contentView()
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(self.H / 2)
        view.layer().setBackgroundColor_(AppKit.NSColor.colorWithWhite_alpha_(0.06, 0.78).CGColor())
        view.layer().setBorderWidth_(0.5)
        view.layer().setBorderColor_(AppKit.NSColor.colorWithWhite_alpha_(1, 0.12).CGColor())
        self.label = AppKit.NSTextField.labelWithString_("")
        self.label.setTextColor_(AppKit.NSColor.colorWithWhite_alpha_(1, 0.9))
        self.label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(12, AppKit.NSFontWeightMedium))
        view.addSubview_(self.label)
        self.bars = []
        for _ in range(self.BARS):
            b = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, self.BAR_W, 3))
            b.setWantsLayer_(True)
            b.layer().setCornerRadius_(self.BAR_W / 2)
            view.addSubview_(b)
            self.bars.append(b)
        self.panel, self._hide_at, self._mode, self._smooth, self._phase = p, None, None, 0.0, 0.0

    def _place(self, width):
        """Bottom centre of the screen with the cursor's active display, just above the Dock."""
        screen = AppKit.NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + (screen.size.width - width) / 2
        self.panel.setFrame_display_(AppKit.NSMakeRect(x, screen.origin.y + 18, width, self.H), True)

    def _set(self, mode, text=""):
        bars_w = self.BARS * self.BAR_W + (self.BARS - 1) * self.GAP
        if mode == "text":
            self.label.setStringValue_(text)
            self.label.sizeToFit()
            width = self.label.frame().size.width + 2 * self.PAD + 4
            self.label.setFrameOrigin_((self.PAD + 2, (self.H - self.label.frame().size.height) / 2))
        else:
            width = bars_w + 2 * self.PAD
        self.label.setHidden_(mode != "text")
        alpha = 0.95 if mode == "listen" else 0.45
        for i, b in enumerate(self.bars):
            b.setHidden_(mode == "text")
            b.layer().setBackgroundColor_(AppKit.NSColor.colorWithWhite_alpha_(1, alpha).CGColor())
            b.setFrame_(AppKit.NSMakeRect(self.PAD + i * (self.BAR_W + self.GAP), (self.H - 3) / 2, self.BAR_W, 3))
        self._place(width)

    def _show(self, mode, text="", seconds=None):
        def ui():
            self._set(mode, text)
            self.panel.orderFrontRegardless()
            self._hide_at = time.time() + seconds if seconds else None
            if seconds:
                AppHelper.callLater(seconds, self._maybe_hide)
            start = self._mode not in ("listen", "busy") and mode in ("listen", "busy")
            self._mode = mode
            if start:
                self._animate()
        AppHelper.callAfter(ui)

    def listening(self):
        self._show("listen")

    def busy(self):
        self._show("busy")

    def say(self, text, seconds=2.5):
        self._show("text", text, seconds)

    def _animate(self):
        """About 30 times a second. Listening: bars follow your voice (rise fast, fall gently). Busy: a slow pulse."""
        if self._mode not in ("listen", "busy"):
            return
        self._phase += 0.3
        top = self.H - 10
        if self._mode == "listen":
            target = self.level()
            self._smooth = target if target > self._smooth else self._smooth * 0.8 + target * 0.2
        for i, b in enumerate(self.bars):
            if self._mode == "listen":
                wobble = 0.7 + 0.3 * math.sin(self._phase + i * 1.1)
                hgt = 3 + top * self._smooth * self.SHAPE[i] * wobble
            else:
                hgt = 3 + 4 * (0.5 + 0.5 * math.sin(self._phase * 0.6 - i * 0.5))
            hgt = max(3.0, min(top, hgt))
            f = b.frame()
            b.setFrame_(AppKit.NSMakeRect(f.origin.x, (self.H - hgt) / 2, self.BAR_W, hgt))
        AppHelper.callLater(1 / 30, self._animate)

    def _maybe_hide(self):
        if self._hide_at and time.time() >= self._hide_at - 0.01:
            self._mode = None
            self.panel.orderOut_(None)

    def hide(self):
        def ui():
            self._mode = None
            self.panel.orderOut_(None)
        AppHelper.callAfter(ui)


# ---------------------------------------------------------------- microphone

class Recorder:
    def __init__(self):
        self.chunks, self.stream, self.rate, self.level = [], None, RATE, 0.0

    def _on_audio(self, data, *_):
        self.chunks.append(data.copy())
        rms = float(numpy.sqrt(numpy.mean(numpy.square(data)))) if len(data) else 0.0
        self.level = min(1.0, rms * 12)  # speech sits around 0.02-0.1 RMS; this maps it onto the bars

    def start(self):
        self.chunks, self.level = [], 0.0
        try:
            self.rate = int(sounddevice.query_devices(kind="input")["default_samplerate"])
            self.stream = sounddevice.InputStream(samplerate=self.rate, channels=1, dtype="float32",
                                                  callback=self._on_audio)
            self.stream.start()
            D.record_use(microphone=True)
            return True
        except Exception as e:  # no microphone, or permission denied
            D.record_use(microphone=False, error="microphone: %s" % type(e).__name__)
            self.stream = None
            return False

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        audio = numpy.concatenate(self.chunks)[:, 0] if self.chunks else numpy.zeros(0, numpy.float32)
        self.chunks = []
        return audio if self.rate == RATE else soxr.resample(audio, self.rate, RATE, quality="HQ")


# ---------------------------------------------------------------- putting text where the cursor is

def focus_info():
    """(name of the app in front, the focused element's role or None, is its value settable, why we couldn't tell).
    The app comes from NSWorkspace (dependable); its focused element from the Accessibility API, after asking
    Electron apps to switch their accessibility tree on (AXManualAccessibility)."""
    front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if front is None:
        return None, None, False, "no app in front"
    name = str(front.localizedName() or front.bundleIdentifier() or "app")
    app = AS.AXUIElementCreateApplication(front.processIdentifier())
    AS.AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)  # harmless where unsupported
    err, el = AS.AXUIElementCopyAttributeValue(app, AS.kAXFocusedUIElementAttribute, None)
    if err or el is None:
        return name, None, False, "app didn't say what has focus (AX %s)" % err
    err, role = AS.AXUIElementCopyAttributeValue(el, AS.kAXRoleAttribute, None)
    serr, settable = AS.AXUIElementIsAttributeSettable(el, AS.kAXValueAttribute, None)
    return name, (None if err else str(role)), bool(settable) if not serr else False, ""


def _key(code, down, flags=0):
    ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
    if flags:
        Quartz.CGEventSetFlags(ev, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _save_clipboard(pb):
    saved = []
    for item in pb.pasteboardItems() or []:
        saved.append({t: item.dataForType_(t) for t in item.types() if item.dataForType_(t) is not None})
    return saved


def _restore_clipboard(pb, saved):
    pb.clearContents()
    items = []
    for kinds in saved:
        it = AppKit.NSPasteboardItem.alloc().init()
        for t, data in kinds.items():
            it.setData_forType_(data, t)
        items.append(it)
    if items:
        pb.writeObjects_(items)


def paste(text):
    pb = AppKit.NSPasteboard.generalPasteboard()
    saved = _save_clipboard(pb)
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
    _key(9, True, Quartz.kCGEventFlagMaskCommand)   # ⌘V
    _key(9, False, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.35)  # let the app read the clipboard before it is put back
    _restore_clipboard(pb, saved)


def type_text(text):
    for i in range(0, len(text), 20):
        part = text[i:i + 20]
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(ev, len(part), part)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.004)


def copy_only(text):
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)


def clean_up(text):
    """Text only (never audio), while Clean up is on (the default): the user's own Claude Code sign-in does the work.
    Any failure keeps the raw transcript."""
    exe = shutil.which("claude", path=os.environ.get("PATH", "") + ":" + os.path.expanduser("~/.local/bin")
                       + ":/opt/homebrew/bin:/usr/local/bin")
    if not exe:
        return text
    try:
        cp = subprocess.run([exe, "-p", "--model", "haiku", CLEANUP_PROMPT], input=text, capture_output=True,
                            text=True, timeout=20)
        out = (cp.stdout or "").strip()
        return out if cp.returncode == 0 and out else text
    except (OSError, subprocess.SubprocessError):
        return text


# ---------------------------------------------------------------- the app

class Dictate:
    def __init__(self):
        from needle.agent.whistle import Whistle
        self.whistle = Whistle(weights=D.weights_path())  # explicit path: never touches the network
        self.cfg = D.settings()
        self.sc = D.SHORTCUTS[self.cfg["shortcut"]]
        self.trigger, self.rec = D.Trigger(), Recorder()
        self.ui = Indicator(lambda: self.rec.level if self.rec.stream is not None else 0.0)
        self.jobs = queue.Queue()
        self.down = False
        threading.Thread(target=self._worker, daemon=True).start()

    # ---- keyboard
    def _is_combo_down(self, kind, code, flags):
        if "key" not in self.sc or code != self.sc["key"]:
            return False
        want = 0
        for m in self.sc["mods"]:
            want |= MOD_FLAGS[m]
        other = 0
        for f in MOD_FLAGS.values():
            other |= f
        return kind == Quartz.kCGEventKeyDown and (flags & other) == want

    def on_event(self, proxy, kind, event, refcon):
        if kind in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self.tap, True)
            return event
        code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        flags = Quartz.CGEventGetFlags(event)
        now = time.time()
        if "modifier" in self.sc:
            if kind == Quartz.kCGEventFlagsChanged and code == self.sc["modifier"]:
                pressed = bool(flags & MOD_FLAG_FOR_KEY[code])
                self._act(self.trigger.press(now) if pressed else self.trigger.release(now))
            elif kind == Quartz.kCGEventKeyDown and code == ESC and self.trigger.listening:
                self._act(self.trigger.esc())
                return None
            return event
        if kind == Quartz.kCGEventKeyDown and code == ESC and self.trigger.listening:
            self._act(self.trigger.esc())
            return None
        if self._is_combo_down(kind, code, flags):
            if not Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
                self.down = True
                self._act(self.trigger.press(now))
            return None  # swallow it: Option+Space must not also type a space
        if kind == Quartz.kCGEventKeyUp and code == self.sc.get("key") and self.down:
            self.down = False
            self._act(self.trigger.release(now))
            return None
        return event

    def _act(self, action):
        if action == "start":
            self.cfg = D.settings()
            if self.rec.start():
                self.ui.listening()
                AppHelper.callLater(0.1, self._tick)
            else:
                self.trigger = D.Trigger()
                self.ui.say("Microphone not available", 3)
        elif action == "stop":
            audio = self.rec.stop()
            self.ui.busy()
            self.jobs.put(audio)
        elif action == "cancel":
            self.rec.stop()
            self.ui.hide()

    def _tick(self):
        if self.trigger.listening:
            self._act(self.trigger.tick(time.time()))
            if self.trigger.listening:
                AppHelper.callLater(0.1, self._tick)

    # ---- transcribe + insert (off the event thread; Whistle is single-threaded, so one worker)
    def _worker(self):
        while True:
            audio = self.jobs.get()
            try:
                if len(audio) < RATE * 0.25:
                    self.ui.hide()
                    continue
                text = (self.whistle.transcribe(audio).get("text") or "").strip()
                del audio  # audio is never kept
                if not text:
                    self.ui.say("Didn't catch that", 1.5)
                    continue
                if self.cfg["cleanup"]:
                    self.ui.busy()
                    text = clean_up(text)
                app, role, settable, why = focus_info()
                where = D.insert_or_copy(app, role, settable)
                if where == "insert":
                    (type_text if self.cfg["insert"] == "type" else paste)(text)
                    self.ui.hide()
                else:
                    copy_only(text)
                    self.ui.say("Copied: press ⌘V", 2.5)
                # what happened and why (never the words), for `lfg dictate status`
                D.record_use(used=True, last={"went": self.cfg["insert"] if where == "insert" else "clipboard",
                                              "app": app or "", "focus": role or why or "unknown"})
            except Exception as e:  # never let one bad dictation stop the helper
                D.record_use(error="transcribe: %s" % type(e).__name__)
                self.ui.say("Dictate hit an error", 2)

    def run(self):
        trusted = AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True})
        D.record_use(accessibility=bool(trusted), error="" if trusted else "Accessibility permission needed")
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
                | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))
        self.tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                           Quartz.kCGEventTapOptionDefault, mask, self.on_event, None)
        if self.tap is None:  # no permission yet: macOS shows the prompt; launchd restarts us
            D.record_use(accessibility=False, error="Accessibility permission needed")
            time.sleep(15)
            sys.exit(1)
        src = Quartz.CFMachPortCreateRunLoopSource(None, self.tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self.tap, True)
        D.record_use(accessibility=True, error="")
        AppHelper.runEventLoop()


def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)  # no Dock icon
    Dictate().run()


if __name__ == "__main__":
    main()
