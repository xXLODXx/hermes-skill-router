# Hermes Skill Router

[![CI](https://github.com/xXLODXx/hermes-skill-router/actions/workflows/ci.yml/badge.svg)](https://github.com/xXLODXx/hermes-skill-router/actions/workflows/ci.yml)

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that makes skill
discovery **task-aware**. It injects a compact, relevance-filtered list of
routing topics and skills into the first turn of every session — so the model
gets a ready-made routing decision instead of scanning the full skill index
and guessing.

```
## Skill Router v2
- productivity/pdf-extraction — required, 0.99 (matrix, name, tag)
- productivity/calendar-sync — recommended, 0.52 (tag)
```

## Features

### Task-aware routing

- **Matrix-gated required skills.** An optional routing matrix declares
  Required/Optional skill packs per topic, and matched topics inject their
  packs. Broad action words such as `review`, `task` and `list` activate a
  topic only with a specific keyword or two corroborating broad signals, so
  unrelated workflow packs stay out.
- **Live catalog scan.** Every message is scored against the tags, name,
  category and description words of **all installed skills, scanned live** —
  newly added skills route without any configuration.
- **Intent-aware dynamic budget.** Three candidates are injected by default;
  the budget grows only for exact user-named skills or qualified
  matrix-required entries, up to six. Excess mandatory skills receive an
  explicit privacy-safe audit reason instead of silently disappearing.
- **Negation-aware.** An explicitly excluded skill (`no plan`, `keinen Plan`,
  `ohne plan`) is rejected rather than elevated by its own name.
- **Complete-token matching.** Short keywords such as `ui` never match inside
  unrelated words such as `Build`; multi-word keywords require all of their
  tokens. Exact hyphenated skill names are recognized directly.
- **Precision-first evidence.** Exact name, tag, description, matrix and
  validated learned signals outrank generic matches; language-neutral
  subword/stem and compound evidence is supporting evidence only and cannot
  trigger an injection by itself.
- **Specificity-weighted scoring.** Tag and description matches are scaled by
  their catalog frequency (`min(1.0, 6/df)`): a word shared by a large part of
  the catalog can neither pass the confidence gate on its own nor crowd the
  candidate budget. Name matches count as explicit signals and stay unscaled.
- **Bounded confidence.** Confidence is a bounded, strictly monotonic squash
  of the calibrated evidence signal (no hard ceiling); corroborated
  multi-kind evidence outranks single-kind scores, and raw scores remain
  inspectable in the audit.
- **Self-maintaining noise suppression.** A small language-neutral stopword
  base plus two statistics-driven filters keep matching clean: words that
  describe most of the catalog (dynamic document-frequency generics) and
  words bound only to base workflow tools (`terminal`, `process`, …) add no
  weight and are pruned from the lexicon. The classifier is recomputed per
  run from the installed skill set, so it adapts as skills change
  (`GENERIC_DF_RATIO`, `SKILL_SELECTIVITY_THRESHOLD`).

### Session behavior

- **Topic-change detection.** A compact match signature is kept per session;
  the injection repeats only when the topic actually changes — same-topic
  follow-ups cost **0 tokens**.
- **Context rescue.** An empty follow-up turn (*"keep going"*) is re-checked
  against the session's bounded recent context (last tool results + assistant
  reply — RAM-only, hard caps); opt out with `SKILL_ROUTER_CONTEXT_RESCUE=0`.
- **First-turn fallback hint.** If nothing matches, the session's first turn
  gets one short hint; later empty turns stay silent and unrelated skills are
  never loaded.
- **Safe hook integration.** Sparse observer hook payloads are accepted
  safely; observer hooks never block the agent turn.

### Routing Observatory (dashboard)

The web dashboard (port 9119) renders the routing pipeline as a modern,
English, theme-aware observatory:

- **Latest route** as a hero panel with a confidence ring and an explicit
  three-stage pipeline: intent signal → evidence review → context ready.
- **Performance grid** — accepted/rejected candidates, confidence, budget and
  fallback signals at a glance.
- **Live decision feed** of recent anonymized events with per-event
  confidence.
- **Framed tile layout** — every section is a framed tile with a background
  fill, built on the dashboard's real theme tokens (`--color-card`,
  `--color-border`, `--midground`, …), following the active Hermes theme in
  dark and light mode.
- **Privacy-safe by design** — only aggregated audit data is rendered: no raw
  prompts, no raw session IDs, no message text.
- Advanced diagnostics stay behind one disclosure.

### Privacy-safe diagnostics

Every routing decision appends a JSONL audit event to
`data/v2_injections.jsonl` with aggregated counts, hashed session
identifiers, confidence, evidence kinds, fallback reasons, catalog size,
profile label, matrix source, rescue/fallback flags, rendered size, stage
status (catalog/matrix availability, candidate count, emission,
deduplication) and the top rejected candidates (name/score/reason). Events
never contain raw user prompts or raw session IDs. The analyzer runs
standalone:

```bash
python scripts/analyze_v2_metrics.py data/v2_injections.jsonl
```

> Note: the dashboard reads the data directory of the plugin copy it was
> launched from, which can differ from the profile whose sessions you are
> inspecting. A zero-event state means “no runtime data yet”, not “plugin
> failed”.

### Multi-profile safety

- The active home resolves through the host's context-local
  `get_hermes_home()` (multiplex-safe), so every session routes with its own
  profile's catalog; standalone fallback order: `HERMES_HOME` env → plugin
  layout → `~/.hermes`.
- Audit records resolve to the session's own profile install, so one
  profile's routing history never accumulates under another profile's data
  directory.
- Symlinked skill trees are followed during the catalog scan.
- The plugin is a dependency-free directory plugin — safe to install across
  multiple profiles without duplicate workspace projects during Hermes
  updates.

### Performance

- Skills-tree walks are TTL-cached (`SKILL_ROUTER_SCAN_TTL`, default 15 s;
  content edits apply instantly, new skills appear within the TTL) and the
  tokenizer is memoized: routing takes **~16 ms** per message.
- Injections use a compact one-line format — **~70 tokens** each
  (⌀ ~276 characters), 0 tokens for same-topic follow-ups.

## Why

- The system-prompt skill index shows only name + truncated description —
  frontmatter **tags are invisible** to the model.
- `always_load: true` in skill frontmatter is **not evaluated by any code**.
- Models routinely miss relevant skills or load wrong ones for a task.

This plugin closes that gap: it hands the model a ready, relevance-filtered
routing decision in the first turn of every session — and stays quiet when it
has nothing useful to add.

## Installation

### Via Hermes (recommended — native plugin install)

```bash
hermes plugins install xXLODXx/hermes-skill-router
hermes plugins enable skill-router
```

### Manually

Copy the repository into your plugins directory and enable it:

```bash
mkdir -p ~/.hermes/plugins/skill-router
cp -r skill_router plugin.yaml ~/.hermes/plugins/skill-router/
hermes plugins enable skill-router
```

Restart Hermes (CLI/TUI/desktop) — plugins load at process start. In
multi-profile setups install into **each** active profile's `plugins/`
directory (`<home>/plugins/skill-router` or
`~/.hermes/profiles/<name>/plugins/skill-router`), keep the copies on the same
version, and restart every affected gateway: the router scans each profile's
own skills directory (symlinked skills are followed via `os.walk(followlinks=True)`).

## Configuration

| Setting | Default | Description |
|---|---|---|
| `SKILL_ROUTER_MATRIX_PATH` (env) | active profile workflow matrix | Optional path to a routing-matrix markdown file (see format below). If unset, the active profile's `skills/software-development/workflow-router/references/workflow-matrix.md` is used when present. |
| `SKILL_ROUTER_CONTEXT_RESCUE` (env) | `1` (on) | Context rescue on/off (`0`/`false`/`no`/`off` disables). RAM-only, bounded. |
| `SKILL_ROUTER_SESSION_TTL` (env) | `3600` | Seconds a session's routing state (dedupe signature, rescue context) is kept in RAM. |
| `HERMES_HOME` (env) | active profile home | Where skills live. Inside Hermes the context-local home wins (multiplex-safe); this env var is the standalone fallback. |

### Routing-matrix format (optional)

A markdown file with numbered topics, keyword lines and Required/Optional
tables, e.g.:

```markdown
## Thema 1: Documents / OCR

**Keywords:** `ocr`, `pdf`, `document`, `scan`

| Kategorie | Skills |
|-----------|--------|
| **Required** | `pdf-extraction`, `action-items` |
| **Optional** | `debugging` |
```

Topics whose keywords match the task are injected with their Required/Optional
skill lists; skills already routed by the matrix are not duplicated in the
auto-suggested section.

## Privacy

- The learned-association files (`learned_keywords.json`, `tool_stats.json`)
  are stored **locally** in the plugin directory and are **never transmitted
  anywhere**.
- It may contain keywords extracted from your own task messages; delete the file
  at any time to reset the learned associations.
- The plugin performs **no telemetry and no network calls**.
- Context rescue keeps the bounded recent tool results / assistant reply **in RAM
  only** (they expire with `SKILL_ROUTER_SESSION_TTL`); nothing is persisted,
  logged or transmitted. Audit events store skill names, counts, hashed session
  IDs and profile labels — never message text.

## Legacy learning engine

The original v1 co-occurrence engine is retained as a compatibility layer.
When present, its data files are visualized in the dashboard:
`learned_keywords.json` (word→tool associations, gated by a lift measure
against chance) and `tool_stats.json` (marginal counts). The live v2 routing
path is precision-first and does not depend on learning data; its optional
output-learning switch is `SKILL_ROUTER_V2_OUTPUT_LEARNING` (default off; the
bounded buffering stays available for context rescue). To disable the legacy
learn path:

```yaml
# config.yaml
skill_router:
  output_learning: false
```

## Development

```bash
pip install -e .[dev]
pytest
```

Tests build a temporary `HERMES_HOME` with fixture skills and verify matching,
matrix parsing, learning and topic-change behavior end-to-end.

## License

MIT — release notes live in [CHANGELOG.md](CHANGELOG.md).
