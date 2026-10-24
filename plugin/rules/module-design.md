Rule module: module-design · LFG · author Varun Singh · adapted from mattpocock/skills/codebase-design (MIT, © 2026 Matt Pocock)

# Module design: deep modules at clean seams

Shared vocabulary for `/plan`, `/build`, `/review-coach` and `/health`. Use these words exactly.

## Vocabulary

- **Module:** anything with an interface and an implementation (function, class, package, slice). Not "component" or "service".
- **Interface:** everything a caller must know: types, invariants, ordering, error modes, config, performance. Not just the signature.
- **Implementation:** the code inside.
- **Depth:** behaviour a caller (or test) gets per unit of interface learned. Deep = lots behind a small interface; shallow = interface about as complex as the body.
- **Seam:** where an interface lives; a place behaviour can change without editing there. Not "boundary".
- **Adapter:** a concrete thing filling a seam (Postgres repo, in-memory fake).
- **Leverage** (for callers) and **locality** (for maintainers: change and bugs concentrate in one place) are what depth buys.

## Principles

- Depth is a property of the interface. A deep module may be built from small parts; they just aren't exposed.
- **Deletion test:** delete the module in your head. If complexity vanishes, it was a pass-through; if it reappears across callers, it earns its keep.
- **The interface is the test surface.** If a test must reach past it, the module is the wrong shape.
- **One adapter = hypothetical seam; two = real seam.** Don't add a port unless something varies across it (usually prod + test).
- Internal seams (for the module's own tests) are not exposed through the interface.

## When designing an interface, ask

- Can there be fewer entry points? Simpler parameters? More hidden inside?
- Does it accept dependencies instead of constructing them?
- Does it return results instead of producing side effects where it can?

## Dependencies decide how the seam is tested

1. **In-process** (pure, in-memory): test through the interface directly.
2. **Local-substitutable** (DB with a local stand-in, in-memory FS): test with the stand-in.
3. **Remote but owned** (your own services): port at the seam; HTTP/queue adapter in prod, in-memory adapter in tests.
4. **True external** (Stripe, Twilio): injected port; mock adapter in tests.

## Deepening existing code

- Replace, don't layer: once tests exist at the deepened interface, delete the old shallow-module tests.
- Tests assert observable outcomes through the interface and survive refactors.

## Design it twice (Full lane, interface genuinely open)

Sketch 2–3 radically different interfaces (minimal entry points · maximum flexibility · trivial common case · ports & adapters). For each: interface, a usage example, what it hides, dependency strategy, trade-offs. Compare on depth, locality and seam placement; recommend one (or a hybrid). Be opinionated.
