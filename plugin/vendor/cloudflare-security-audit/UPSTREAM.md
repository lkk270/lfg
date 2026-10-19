# Vendored: Cloudflare security-audit skill

- Source: https://github.com/cloudflare/security-audit-skill (`skills/security-audit/` and `LICENSE`)
- Pinned commit: `c1c8a8c1471069fb0e188eeaff69b8e8db6564a8`
- Licence: MIT, see `LICENSE` (© Cloudflare, Inc.)
- Vendored 2026-10-14 for LFG by Varun Singh. Files are byte-for-byte upstream; the `*.test.cjs` files were left out.

This folder is not a Claude Code skill (it is outside `plugin/skills/`). `/secure` and the security-analyst agent read
it as method guidance. The two validators are plain Node scripts that only read the file they are given
(`fs`, `path`, `util`; no network, no child processes, no writes).

## How LFG uses it

| Upstream | In LFG |
|---|---|
| Guidance mode | `/secure` diff review of security-sensitive code: core principles, severity anchors, `needs_validation`, and the domain companions the diff touches |
| Full audit mode | `/secure audit [quick\|standard\|deep] [paths]`, only when the user types it, after an agreed agent budget |
| Output directory outside the target | `<scratch>/security-audit/` (`lfg run scratch`: under `~/.lfg/runs/`, never in the repo; the run folder itself is in the repo and committed) |
| OS-enforced sandbox for target code | LFG provides none, so target code is never executed. Leads stay `needs_validation`; `/pentest` (Strix, offline, local Ollama) is the route to dynamic confirmation |
| `confirmed` findings | Mapped into `05-secure.json` and dev-graph `Issue` (type `risk`); human decisions at checkpoint 3 |

## Updating

Re-pin only after reading the upstream diff. Fetch the new commit into an empty temp folder, re-vet the `.cjs`
validators (requires and file writes), copy the files here, then update the commit above and the checksums below
(`shasum -a 256 *` without this file). `tests/test_core.py` fails when a file differs from its checksum.

## SHA-256

```
7335a95c43554eadefcf03ece639291bb0e038c398a179299e3887ffe06bd2ef  AI-AND-LLM.md
3ee4f00c6e8c9dcf6dd02dd5ac2a4ceb322e2085f3e9fbe79cf0c6330bc7ef83  ATTACK-CLASSES.md
613f6b98f86083e045525c5b60154ffdab122bac35f1e05eb17488e6e453370c  CLIENT-SIDE.md
3c80f3088be22345e07b057c056d6ed99fe2b0304f794398964f7ccd5a496ca3  CLOUD-AND-DEPLOYMENT.md
307dcb3e24d292715c4a041190e7bb135646a37eb6187619ae01d000a634a4ad  DATA-ISOLATION-AND-LIFECYCLE.md
58eae8ee0ca6a46611c501ec5a3ab47fdff88dd7db0d8d74789bbf8bb19d8cb2  DESKTOP-MOBILE-AND-LOCAL-IPC.md
71c121decea1322c47c718f6e110f1a892980bb4266bd7ac55ef043a213ade09  HUNTING.md
e598e694aa506650c7192d5ea3be0e50aca0d356ea00551c53429f0b01eb6391  LICENSE
7c8b0dccfb35315cca2455509674d49632b2fe37e1f3aac16c1a496a7e9924a7  MEMORY-SAFETY-AND-BINARY.md
8b73816fa5b3697c9c40977f0c836b40f01d6e81929ff2720fe83ce089e9a619  PROTOCOLS-RPC-AND-MESSAGING.md
02ca887aca84de8ae137f1891bd2f0a54f28d3fa6da92a27f54734382b3381a2  RECONNAISSANCE.md
4326fab5c92a0b4c420a70196254040105cd794026562130b59bf1a6db3e4baa  RESOURCE-EXHAUSTION-AND-AVAILABILITY.md
5e3e96a1e438d8f35fef0a1e38f02d4f00e2bdf910401b7dfe00e6779c6dac85  SKILL.md
f372e919940e335468ba1ae09f99026c3986a345f7fe26f8068f132e199f52a5  SUPPLY-CHAIN-AND-RELEASE.md
b892470cb89bb31f33403e050d4bdfbe2cdaef940ade1496fa65e32b2e129449  VALIDATION-AND-REPORTING.md
4f3066dffa23c5635859187be9b96c32f2aff29a688186b91ff0c63e47d62b5c  WEB-PROTOCOL-AND-AUTH.md
6575c9de4a62255699ea052ebf9a49ebfb373a32891bcd89af6f55cc84b35519  report-schema.json
2eb280bd2e33c002916f86db9b29f9edfedb6454e5db973c766290465b868ac8  validate-coverage-ledger.cjs
e85f232e36bfac0f866f244da50376692d6b45c690beadcb00608b0e6c8b5283  validate-findings.cjs
```
