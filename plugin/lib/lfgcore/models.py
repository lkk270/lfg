"""The Claude models Studio and reviews can run on: one list, so the two pickers never drift apart."""
import os

from . import common as C

MODELS = [("claude-fable-5-2", "Fable 5.2"), ("claude-mythos-5-2", "Mythos 5.2"), ("claude-fable-5-1", "Fable 5.1"),
          ("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-haiku-5-5", "Haiku 5.5")]
ALIASES = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}  # older state files hold these


def own_model():
    """The model Claude Code's own settings pick ("" when none)."""
    return (C.read_json(os.path.join(C.HOME, ".claude", "settings.json"), {}) or {}).get("model") or ""


def choices(own=""):
    """The model picker: Claude Code's default first (named when `own` is set), then every model."""
    return [{"id": "", "label": "Claude Code default" + (" (%s)" % own if own else "")}] + [
        {"id": i, "label": lb} for i, lb in MODELS]


def label(model_id):
    """A name a person knows for a model id."""
    if not model_id:
        return "Claude Code default"
    if model_id in ALIASES:
        return ALIASES[model_id]
    known = dict(MODELS)
    if model_id in known:
        return known[model_id]
    return " ".join(model_id.removeprefix("claude-").replace("-", " ").split())


def valid(model_id):
    """True for "", a listed model id or an older alias."""
    return not model_id or model_id in dict(MODELS) or model_id in ALIASES
