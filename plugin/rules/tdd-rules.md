Rule module: tdd-rules · LFG · author Varun Singh · adapted from mattpocock/skills/tdd (MIT, © 2026 Matt Pocock)

# TDD rules

Red → green, one slice at a time, with tests worth keeping. Applies to `/build`, `/fix` and every implementer subagent.

## Before the first test

- Read the glossary (`lfg repo docs` → `GLOSSARY.md`) so test names use the domain's words; respect ADRs in the area.
- **Seams.** Test only at agreed seams: the public interface where behaviour is observable without reaching inside.
  - **Unattended** (inside `/lfg`, `/wizard`, a subagent, or any ticket that has `test_seams` in `tasks.json`): use exactly the ticket's `test_seams`. Do not ask. If a needed seam is missing, use the highest existing seam the graph shows (`query_graph_tool` `tests_for`) and record it in `03-build-<id>.md` under "Seam added".
  - **Interactive, no agreed seams:** propose seams, one line each on what it catches and what it misses, and confirm with the user before writing a test.
- Prefer existing seams and the highest seam that observes the behaviour. Fewer seams is better.
- If the interface shape itself is in question, load `lfg rule module-design`.

## The loop

1. Write **one** failing test for the next behaviour. Run it; see it fail for the right reason.
2. Write only enough code to pass it. No speculative features, no anticipating the next test.
3. Run it; see it pass. Type-check and re-run the touched test files.
4. Repeat. Each test is a tracer bullet that reacts to what the last cycle taught you.
- Refactoring is not part of this loop; it belongs to `/review-coach` feedback.
- At the end: affected tests (`tests_for` on changed nodes), then the full suite once.

## A good test

- Exercises behaviour through the public interface; reads like a spec ("user can export invoices as CSV").
- Survives internal refactors; describes WHAT, not HOW; one logical assertion.
- Expected values come from an independent source: a literal, a worked example, the acceptance criterion.
- Verifies through the interface (create, then fetch through the API), not a side channel (raw DB query).

## Anti-patterns (reject in your own work and in review)

- **Implementation-coupled:** mocks internal collaborators, tests private methods, asserts call counts/order.
- **Tautological:** expected value recomputed the way the code does it, so it can never disagree.
- **Horizontal slicing:** all tests first, then all code. Work vertically instead.

## Mocking

- Mock only at system boundaries: third-party APIs, time, randomness; sometimes the DB (prefer a local test DB) and filesystem.
- Never mock your own modules or internal collaborators.
- Make boundaries mockable: inject dependencies instead of constructing them inside; prefer one function per external operation (SDK-style) over a generic `fetch(endpoint)` wrapper.
- Credentials in tests come from env vars by name or obvious placeholders (`sk-test-<REDACTED>`), never real-looking values.

## Never

- Skip, delete, `.only`, or weaken a test to get green. If a test is wrong, say so and ask.
- Add `@ts-ignore`, `eslint-disable`, `# noqa`, `.skip(`, `xit(`, `@pytest.mark.skip`.
