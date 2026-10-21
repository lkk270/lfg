"""LFG Dictate: press a shortcut anywhere on the Mac, speak, and the words appear where the cursor is.

Ships dormant. Nothing is downloaded, installed or asked for until the user turns it on (`lfg add dictate` or the
dashboard). Turning it on builds a private environment in ~/.lfg/dictate (cactus-needle + the macOS bindings), fetches
the Whistle model and its engine there, and starts a login agent (dev.lfg.dictate, recorded in the change ledger) that
runs dictate_helper.py. Everything runs on-device: the helper starts with telemetry off and Hugging Face offline, and
loads the model from an explicit path, so no audio or usage count leaves the Mac. Clean up (on by default; off in
Settings or `lfg dictate cleanup off`) sends the transcribed text, never audio, to Claude with the user's Claude Code
sign-in; if that fails the raw text is used. No audio and no transcript is kept. Turning it off removes the agent
and the whole folder.

This module is standard-library only (it runs inside LFG); the helper imports the pure parts (Trigger, shortcuts).
"""
import json
import os
import shutil
import sys
import time

from . import claudecfg as CC
from . import common as C

LABEL = "dev.lfg.dictate"
NEEDLE = "cactus-needle[mic]==3.2.8"
BINDINGS = ["pyobjc-framework-Quartz", "pyobjc-framework-Cocoa", "pyobjc-framework-ApplicationServices"]
OFFLINE_ENV = {"NEEDLE_TELEMETRY": "0", "DO_NOT_TRACK": "1", "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}

# Shortcut presets. A combo is a key code plus modifiers; a lone modifier (Fn, Right Option) is watched on its own.
SHORTCUTS = {
    "option+space": {"label": "Option + Space", "key": 49, "mods": ["alt"]},
    "ctrl+space": {"label": "Control + Space", "key": 49, "mods": ["ctrl"]},
    "cmd+shift+space": {"label": "Command + Shift + Space", "key": 49, "mods": ["cmd", "shift"]},
    "fn": {"label": "Fn (globe)", "modifier": 63},
    "right_option": {"label": "Right Option", "modifier": 61},
}
DEFAULT_SHORTCUT = "option+space"


def home(*parts):
    return C.lfg_path("dictate", *parts)


def venv_python():
    return home("venv", "bin", "python")


def weights_path():
    return home("whistle.cact")


def engine_path():
    return home("engine", "libneedle.dylib")


def helper_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictate_helper.py")


APP_NAME = "LFG Dictate"
BUNDLE_ID = "dev.lfg.dictate"
MIC_REASON = ("LFG Dictate listens only while you hold your Dictate shortcut (or after you double-tap it), and turns "
              "your speech into text on this Mac. Audio never leaves the Mac and is never saved.")


def app_path():
    return home(APP_NAME + ".app")


def launcher_path():
    return os.path.join(app_path(), "Contents", "MacOS", "lfg-dictate")


# The app's executable: starts the helper as its child, so macOS treats the helper as part of "LFG Dictate" (the
# Microphone and Accessibility prompts and System Settings show that name, not "python"), forwards stop signals and
# exits with the helper's status so launchd restarts it when needed.
LAUNCHER_C = r"""
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
extern char **environ;
static pid_t child = 0;
static void forward(int sig) { if (child > 0) kill(child, sig); }
int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: lfg-dictate <program> [args...]\n"); return 2; }
    signal(SIGTERM, forward); signal(SIGINT, forward); signal(SIGHUP, forward);
    if (posix_spawn(&child, argv[1], NULL, NULL, argv + 1, environ) != 0) { perror("lfg-dictate"); return 1; }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
"""

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>%(name)s</string>
  <key>CFBundleDisplayName</key><string>%(name)s</string>
  <key>CFBundleIdentifier</key><string>%(id)s</string>
  <key>CFBundleExecutable</key><string>lfg-dictate</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>%(version)s</string>
  <key>CFBundleShortVersionString</key><string>%(version)s</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSMicrophoneUsageDescription</key><string>%(mic)s</string>
</dict></plist>
"""


def build_app(log=print):
    """~/.lfg/dictate/LFG Dictate.app: Info.plist + the launcher, compiled here and signed ad hoc. Returns False (and
    Dictate falls back to running the helper directly, named "python" by macOS) when there is no compiler."""
    from .setup import which
    cc = which("clang") or which("cc")
    if not cc:
        log("    no C compiler (install the Xcode command line tools for the \"LFG Dictate\" name in macOS prompts)")
        return False
    macos = os.path.dirname(launcher_path())
    C.ensure_dir(macos, 0o755)
    C.write_text(os.path.join(app_path(), "Contents", "Info.plist"),
                 INFO_PLIST % {"name": APP_NAME, "id": BUNDLE_ID, "version": C.VERSION, "mic": MIC_REASON},
                 mode=0o644)
    src = home("launcher.c")
    C.write_text(src, LAUNCHER_C, mode=0o644)
    cp = C.run([cc, "-O2", "-o", launcher_path(), src], timeout=120)
    os.remove(src)
    if cp.returncode:
        log("    could not build the LFG Dictate app (%s); using the helper directly" % cp.stderr.strip()[-200:])
        return False
    C.run(["codesign", "--force", "--sign", "-", "--identifier", BUNDLE_ID, app_path()], timeout=120)
    return True


def settings():
    d = C.config().get("dictate") or {}
    shortcut = d.get("shortcut") if d.get("shortcut") in SHORTCUTS else DEFAULT_SHORTCUT
    return {"shortcut": shortcut, "insert": "type" if d.get("insert") == "type" else "paste",
            "cleanup": bool(d.get("cleanup", True))}


def installed():
    return all(os.path.isfile(p) for p in (venv_python(), weights_path(), engine_path()))


# ---------------------------------------------------------------- the trigger: hold to talk, double-tap hands-free

class Trigger:
    """What a press, release, Esc or the passing of time means. Pure logic, so it is tested without a keyboard.

    Hold the shortcut for at least HOLD seconds: push-to-talk, stops (and inserts) on release. Tap it twice within
    DOUBLE seconds: hands-free until the next press or Esc. A single short tap is ignored (recording is cancelled).
    Actions: "start" (open the microphone), "stop" (transcribe and insert), "cancel" (discard), or None.
    """
    HOLD = 0.35
    DOUBLE = 0.40

    def __init__(self):
        self.state, self.t = "idle", 0.0

    def press(self, now):
        if self.state == "idle":
            self.state, self.t = "held", now
            return "start"
        if self.state == "maybe_double":
            if now - self.t <= self.DOUBLE:
                self.state = "handsfree"
                return None
            self.state, self.t = "held", now  # too late for a double tap: a fresh hold
            return None
        if self.state == "handsfree":
            self.state = "closing"  # its release is swallowed
            return "stop"
        return None

    def release(self, now):
        if self.state == "held":
            if now - self.t >= self.HOLD:
                self.state = "idle"
                return "stop"
            self.state, self.t = "maybe_double", now
            return None
        if self.state == "closing":
            self.state = "idle"
        return None

    def tick(self, now):
        if self.state == "maybe_double" and now - self.t > self.DOUBLE:
            self.state = "idle"
            return "cancel"
        return None

    def esc(self):
        if self.state in ("held", "handsfree", "maybe_double"):
            self.state = "idle"
            return "stop"
        return None

    @property
    def listening(self):
        return self.state in ("held", "maybe_double", "handsfree")


# ---------------------------------------------------------------- insert or leave on the clipboard

TEXT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXWebArea", "AXSecureTextField"}
NOT_TEXT_ROLES = {"AXButton", "AXCheckBox", "AXRadioButton", "AXMenuItem", "AXMenuBarItem", "AXImage", "AXList",
                  "AXOutline", "AXTable", "AXBrowser", "AXDockItem", "AXSlider", "AXPopUpButton"}


def insert_or_copy(focused_app, role, settable):
    """Where dictated text goes: paste (or type) it, unless macOS positively says the focused thing is not editable
    (a button, list, image...). Not knowing is common (Chrome, Electron apps such as Slack, VS Code or Claude, Java
    apps, and macOS sometimes won't even say which app is in front), and not knowing means insert: pasting where
    nothing takes text is harmless, and the user expects the words where their cursor is."""
    if role in NOT_TEXT_ROLES and not settable:
        return "clipboard"
    return "insert"


# ---------------------------------------------------------------- shortcut clashes

def conflicts(shortcut):
    """Apps known to claim a shortcut by default. macOS has no API to list other apps' hotkeys, so this checks the
    usual suspects; the helper also reports if it never sees the shortcut."""
    apps = {"option+space": [("ChatGPT", "/Applications/ChatGPT.app"), ("Raycast", "/Applications/Raycast.app"),
                             ("Alfred", "/Applications/Alfred 5.app")],
            "ctrl+space": [("macOS input source switching", None)],
            "cmd+shift+space": [], "fn": [("macOS emoji / dictation key (System Settings › Keyboard)", None)],
            "right_option": []}
    out = []
    for name, path in apps.get(shortcut, []):
        if path is None or os.path.isdir(path):
            out.append(name)
    return out


def suggestion(shortcut):
    for s in ("right_option", "cmd+shift+space", "option+space"):
        if s != shortcut and not conflicts(s):
            return s
    return None


# ---------------------------------------------------------------- install / remove (only when the user turns it on)

def _plist():
    env = dict(OFFLINE_ENV, LFG_HOME=C.LFG_HOME, NEEDLE3_LIB_PATH=engine_path(), HF_HOME=home("hf"),
               PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    envx = "".join("<key>%s</key><string>%s</string>" % kv for kv in sorted(env.items()))
    log = home("helper.log")
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key><array>%s<string>%s</string><string>%s</string></array>
  <key>EnvironmentVariables</key><dict>%s</dict>
  <key>WorkingDirectory</key><string>%s</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
</dict></plist>
""" % (LABEL, "<string>%s</string>" % launcher_path() if os.path.isfile(launcher_path()) else "", venv_python(),
       helper_path(), envx, home(), log, log)


def _plist_path():
    return os.path.join(C.HOME, "Library", "LaunchAgents", LABEL + ".plist")


def _target():
    return "gui/%d/%s" % (os.getuid(), LABEL)


def agent_loaded():
    return C.run(["launchctl", "print", _target()]).returncode == 0


PREFETCH = """
import os, sys
from needle.agent import fetch
d = sys.argv[1]
fetch.fetch_library(dest_dir=os.path.join(d, "engine"), generation=3)
fetch.fetch_weights(fetch.WHISTLE, dest_dir=d)
"""


def install(log=print):
    """Build ~/.lfg/dictate, fetch the model, start the helper. Called by `lfg add dictate` / the dashboard."""
    if sys.platform != "darwin":
        raise RuntimeError("LFG Dictate supports macOS only for now")
    from .setup import which
    uv = which("uv")
    if not uv:
        raise RuntimeError("uv is needed to set up Dictate (it comes with Core: run `lfg setup`)")
    C.ensure_dir(home())
    if not os.path.isfile(venv_python()):
        log("    creating Dictate's private environment in %s" % home("venv"))
        _run(log, [uv, "venv", "-q", "--python", "3.12", home("venv")])
    log("    installing the speech engine and macOS bindings")
    _run(log, [uv, "pip", "install", "-q", "--python", venv_python(), NEEDLE] + BINDINGS)
    if not (os.path.isfile(weights_path()) and os.path.isfile(engine_path())):
        log("    downloading the Whistle model (17 MB) and its engine")
        env = dict(os.environ, NEEDLE_TELEMETRY="0", DO_NOT_TRACK="1", HF_HOME=home("hf"), HOME=home())
        cp = C.run([venv_python(), "-c", PREFETCH, home()], env=env, timeout=900)
        if cp.returncode:
            raise RuntimeError("model download failed: %s" % (cp.stderr or cp.stdout).strip()[-400:])
        shutil.rmtree(home("hf"), ignore_errors=True)  # the download cache; the files we need were copied out
    if not os.path.isfile(launcher_path()) or C.read_text(os.path.join(app_path(), "Contents", "Info.plist")).find(
            "<string>%s</string>" % C.VERSION) < 0:
        log("    building the LFG Dictate app (so macOS asks for permission as \"LFG Dictate\")")
        build_app(log)
    p = _plist_path()
    want = _plist()
    if C.read_text(p) != want:
        C.run(["launchctl", "bootout", _target()])
        C.ensure_dir(os.path.dirname(p), 0o755)
        C.write_text(p, want, mode=0o644)
        CC.file_created(p, "LFG Dictate helper login agent", "dictate", tag="dictate-agent",
                        undo=["launchctl", "bootout", _target()])
    if not agent_loaded():
        cp = C.run(["launchctl", "bootstrap", "gui/%d" % os.getuid(), p])
        if cp.returncode:
            raise RuntimeError("launchctl bootstrap failed: %s" % cp.stderr.strip())
    notes = ["Dictate is on: hold %s anywhere to talk, double-tap for hands-free. macOS will ask for Microphone and "
             "Accessibility permission for \"%s\" the first time." % (SHORTCUTS[settings()["shortcut"]]["label"],
                                                                    APP_NAME if os.path.isfile(launcher_path())
                                                                    else "python")]
    clash = conflicts(settings()["shortcut"])
    if clash:
        alt = suggestion(settings()["shortcut"])
        notes.append("%s may also use %s; if it does, pick another shortcut in Settings%s." % (
            ", ".join(clash), SHORTCUTS[settings()["shortcut"]]["label"],
            " (e.g. %s)" % SHORTCUTS[alt]["label"] if alt else ""))
    C.audit("dictate-on", {})
    return notes


def uninstall():
    """Stop the helper, remove its agent (through the ledger) and delete ~/.lfg/dictate with the model."""
    CC.undo_where(tag="dictate-agent")
    C.run(["launchctl", "bootout", _target()])
    if os.path.exists(_plist_path()):
        os.remove(_plist_path())
    shutil.rmtree(home(), ignore_errors=True)
    C.audit("dictate-off", {})
    return {"removed": True}


def restart():
    return agent_loaded() and C.run(["launchctl", "kickstart", "-k", _target()]).returncode == 0


def set_option(key, value):
    """`lfg dictate cleanup on|off`, `insert paste|type`, `shortcut <preset>`: saved and validated like the dashboard
    (settings.save_config), which restarts the helper so it takes effect at once."""
    from . import settings as S
    if key == "cleanup":
        if value not in ("on", "off"):
            raise S.Invalid("use: lfg dictate cleanup on|off")
        return S.save_config({"dictate.cleanup": value == "on"})
    if key in ("insert", "shortcut"):
        return S.save_config({"dictate." + key: value})
    raise S.Invalid("unknown Dictate option %r" % key)


def status():
    st = C.read_json(home("state.json"), {}) or {}
    today = time.strftime("%Y-%m-%d")
    s = settings()
    return {"installed": installed(), "agent": agent_loaded() if installed() else False,
            "shortcut": s["shortcut"], "shortcut_label": SHORTCUTS[s["shortcut"]]["label"], "insert": s["insert"],
            "cleanup": s["cleanup"], "accessibility": st.get("accessibility"), "microphone": st.get("microphone"),
            "error": st.get("error") or "", "today": st.get("count", 0) if st.get("day") == today else 0,
            "last": st.get("last") or {},
            "conflicts": conflicts(s["shortcut"])}


def _run(log, argv):
    cp = C.run(argv, timeout=1800)
    if cp.returncode:
        raise RuntimeError("`%s` failed: %s" % (" ".join(os.path.basename(a) for a in argv[:3]),
                                              ((cp.stderr or "") + (cp.stdout or "")).strip()[-400:]))
    return cp


def record_use(accessibility=None, microphone=None, error=None, used=False, last=None):
    """The helper's status file: permissions, last error and today's count. Never any words or audio."""
    p = home("state.json")
    st = C.read_json(p, {}) or {}
    today = time.strftime("%Y-%m-%d")
    if st.get("day") != today:
        st = {k: v for k, v in st.items() if k not in ("day", "count")}
        st.update(day=today, count=0)
    if used:
        st["count"] = st.get("count", 0) + 1
    for k, v in (("accessibility", accessibility), ("microphone", microphone), ("error", error), ("last", last)):
        if v is not None:
            st[k] = v
    C.ensure_dir(home())
    with open(p + ".tmp", "w") as f:
        json.dump(st, f)
    os.replace(p + ".tmp", p)
