"""The Claude models Studio and reviews can run on: one list, so the two pickers never drift apart."""
MODELS = [("claude-fable-5-2", "Fable 5.2"), ("claude-mythos-5-2", "Mythos 5.2"), ("claude-fable-5-1", "Fable 5.1"),
          ("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-haiku-5-5", "Haiku 5.5")]
ALIASES = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}  # older state files hold these


def choices():
    """The model picker: Claude Code's default first (never named: its settings file does not say what it runs),
    then every model."""
    return [{"id": "", "label": "Claude Code default"}] + [{"id": i, "label": lb} for i, lb in MODELS]


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


def shown(model_id, said=""):
    """The name a session's model goes by: the picked model's, else the model it is really running (the one its last
    reply used, `said`), else plain "Claude Code default"."""
    return label(model_id or said)


def note(model_id, said=""):
    """The tooltip for a session on Claude Code's default: what it runs on ("" when a model was picked or none is
    known)."""
    return "" if model_id or not said else "Running on %s (Claude Code's default)" % label(said)


def valid(model_id):
    """True for "", a listed model id or an older alias."""
    return not model_id or model_id in dict(MODELS) or model_id in ALIASES
