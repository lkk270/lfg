Probe, 2026-11-17, real `claude` CLI in a throwaway temp folder, `-p --input-format stream-json --output-format stream-json --verbose`.
A `control_request` `set_model` with `claude-haiku-5-5` after `initialize` was answered `success` with `{"model": "claude-haiku-5-5"}`.
The next message got a `system init` and assistant messages with `model: claude-haiku-5-5`, so `Live._native_set_model` defaults to True.
