# Hermes Skill Router

[![CI](https://github.com/xXLODXx/hermes-skill-router/actions/workflows/ci.yml/badge.svg)](https://github.com/xXLODXx/hermes-skill-router/actions/workflows/ci.yml)

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that makes skill
discovery **task-aware**. It injects a compact, relevance-filtered list of
routing topics and skills into the first turn of every session — so the model
no longer has to scan the full skill index and guess. (v0.800: profile-safe
home resolution, token-compact output, context rescue; the original
self-learning engine is retained as a legacy compatibility layer.)

```
## Skill Router v2
- productivity/pdf-extraction — required, 0.99 (matrix, name, tag)
- productivity/calendar-sync — recommended, 0.52 (tag)
```

## What's new in 0.8.6

- **Compact diagnostic stage status** — each privacy-safe audit event now
  records catalog availability, matrix availability and match count, selector
  candidate count, emission, and deduplication. This identifies the first
  routing stage that needs investigation without storing message text.

## What's new in 0.8.5

- **Matrix keywords now require complete tokens** — short keywords such as
  `ui` no longer match inside unrelated words such as `Build`; multi-word
  keywords require all of their tokens. This prevents false mandatory skill
  injections while preserving normal matrix routing.

## What's new in 0.8.4

- **Ranking confidence no longer saturates** — confidence now uses a bounded,
  strictly monotonic squash of the calibrated evidence signal instead of a
  hard `0.99` ceiling. Higher calibrated evidence therefore remains visible to
  consumers, while the existing cross-kind corroboration preference is
  retained.
- **Raw scores are inspectable** — `CandidateDecision` now exposes `score`
  and `exact_score` alongside confidence, and audit records include accepted
  score aggregates plus raw scores for top rejected candidates.
- **Regression coverage** — tests cover former ceiling collisions and the
  ranking boundary where corroborated multi-kind evidence should outrank a
  slightly larger single-kind score.

## What's new in 0.8.3

- **Performance pass** — the skills-tree walk is TTL-cached (`SKILL_ROUTER_SCAN_TTL`,
  default 15 s; content edits still apply instantly, new skills appear within the TTL):
  `scan_catalog` **18.5 ms → 0.8 ms** per turn, tokenizer memoized (`select()`
  20.4 → **14.9 ms**), the routing path drops from ~39 ms to **~16 ms** per message.
  The dashboard's legacy skill scan now follows symlinked directories (profile layouts
  were under-reported) and `runtime-metrics` is mtime-cached.

## What's new in 0.8.2

- **Specificity-weighted evidence** — tag and description matches are scaled by their
  catalog frequency (`min(1.0, 6/df)`): a word shared by a large part of the catalog can
  no longer pass the confidence gate on its own or crowd the candidate budget. Name
  matches are treated as explicit signals and stay unscaled. Measured on the real
  catalogs (195/57/127 skills): gate passers per task drop (e.g. 35→26, 13→4, 18→12,
  9→2), budget rejections collapse (API audit: 10→1), and the top hits stay stable.

## What's new in 0.8.1

- **Session-scoped audit placement** — on multi-profile hosts (one process serving several
  profiles), audit records now resolve to the **session's own profile install**
  (`<home>/plugins/skill-router/data/`) and only fall back to the loaded copy, so one
  profile's routing history never accumulates under another profile's data directory.

## What's new in 0.800

- **Profile-safe home resolution** — the active home is resolved through the host's
  context-local `get_hermes_home()` (fallbacks: `HERMES_HOME` → plugin layout →
  `~/.hermes`), so every session routes with **its own profile's catalog**. Fixes a
  verified cross-profile leak where a default-profile session could be routed with
  another profile's skills.
- **Token-optimized injections** — compact one-line format, measured **~25 % smaller**
  (avg 369 → 276 characters across 236 live injections, ≈ ~70 tokens each); follow-ups
  on the same topic stay at 0 tokens.
- **Context rescue** — an empty follow-up turn (*"keep going"*) is re-checked against
  the session's bounded recent context (last tool results + assistant reply — RAM-only,
  hard caps; on by default, disable with `SKILL_ROUTER_CONTEXT_RESCUE=0`).
- **First-turn fallback hint** — if nothing matches, the first turn gets one short hint;
  later empty turns stay silent and unrelated skills are never loaded.
- **Enriched audit** — every event now carries `catalog_size`, `profile`, `matrix_source`,
  `rescue`, `fallback_emitted`, `rendered_chars` and the **top rejected candidates**
  (name/score/reason) — configuration or binding problems become visible at a glance.
- **Faster per turn** — catalog and matrix are cached per file revision (mtime + size);
  no more re-reading of every `SKILL.md` on each turn.
- **Single-source version** — read from `plugin.yaml` in audit and dashboard alike;
  `SKILL_ROUTER_SESSION_TTL` makes the session-state lifetime configurable.
- **Healthier tests** — suites no longer write into the real data directory; the mirror
  test understands profile-local installations.

Full details: [CHANGELOG.md](CHANGELOG.md).

## Why

- The system-prompt skill index shows only name + truncated description —
  frontmatter **tags are invisible** to the model.
- `always_load: true` in skill frontmatter is **not evaluated by any code**.
- Models routinely miss relevant skills or load wrong ones for a task.

This plugin closes that gap with three mechanisms:

1. **Task matching** — the user's message is scored against (a) the keywords of an
   optional routing matrix and (b) the tags, name, category and description words
   of **all installed skills, scanned live** (new skills are picked up automatically).
2. **Topic-change detection** — a compact match signature is kept per session;
   the injection repeats only when the topic actually changes (token-saving).
   No match → a single short fallback hint on the first turn of the session.
3. **Context rescue** — a follow-up turn that matches nothing on its own
   (e.g. *"mach weiter"*) is re-checked against the bounded recent context of
   the same session (last tool results + assistant reply, RAM-only, hard
   caps). Indirect tasks like *"check the kanban board and work through the
   tasks"* still find their skills — without writing anything to disk.
4. **Causal weighting & self-cleaning (legacy v1 engine)** — raw co-occurrence counts are gated by
   a lift measure (observed / expected-by-chance). Words that appear before
   every tool (e.g. "bitte", "schnell") get lift ~1 and weight nothing; words
   that reliably precede one tool (e.g. "emulator" → adb tools) get weight.
   The lexicon is pruned on every save: entries without any causal association
   are removed. Marginal counts live in `tool_stats.json`. In the v0.800
   runtime these learning paths are inactive; the dashboard still visualizes
   existing files.

## V2 routing and diagnostics

Version 0.800 uses a precision-first selector for the live routing path:

- Exact name, tag, description, matrix and validated learned signals outrank generic matches.
- Language-neutral subword/stem and compound evidence is supporting evidence only; it cannot trigger an injection by itself.
- At most three automatically discovered candidates are injected per event. Matrix-declared **Required/Pflicht** skills are exempt from that discovery budget, so mandatory workflow skills cannot be silently dropped; optional and inferred candidates remain capped and are recorded as rejections.
- If no candidate reaches the confidence gate, the first turn of a session gets a single short fallback hint; later empty turns stay silent — unrelated skills are never loaded.
- Context rescue (see above) rescues empty follow-up turns from the session's own bounded context; opt out with `SKILL_ROUTER_CONTEXT_RESCUE=0`.
- The active home resolves through the host's context-local `get_hermes_home()` (multiplex-safe), so every profile routes with its own catalog; standalone fallback order: `HERMES_HOME` env → plugin layout → `~/.hermes`.
- The injected block uses a compact format: `- <path> — <decision>, <confidence> (<kinds>)` — measured ~25 % smaller than the 0.7.x label format (236 live injections).
- Sparse observer hook payloads are accepted safely; observer hooks do not block the agent turn.

The plugin writes privacy-safe JSONL diagnostics to `data/v2_injections.jsonl`. Events contain aggregated counts, hashed session identifiers, confidence, evidence kinds, fallback reasons, **catalog size, profile label, matrix source, rescue/fallback flags, rendered size** and the top rejected candidates (name/score/reason — the tuning input for future releases) — never raw user prompts or raw session IDs. The analyzer can be run independently:

```bash
python scripts/analyze_v2_metrics.py data/v2_injections.jsonl
```

The dashboard's **Mission Control** view separates live routing health from the historical learning store. It shows the runtime version, routing funnel, accepted/rejected candidates, fallbacks, confidence, evidence profile, the per-event **profile** and **catalog size** (a quick way to spot cross-profile binding problems) and recent anonymized decisions. Note: the dashboard reads the data directory of the copy it was loaded from (its launch home), which can differ from the profile whose sessions you are inspecting. A zero-event state means “no runtime data yet”, not “plugin failed”.

Typical cost: **~70 tokens per injection ⌀** (compact format, ⌀ ~276 chars), 0 tokens for follow-ups on the same topic, and at most one short fallback hint or one rescued injection per session boundary case.

## Installation

### Via Hermes (recommended — native plugin install)

```bash
hermes plugins install xXLODXx/hermes-skill-router
hermes plugins enable skill-router
```

### Via pip

```bash
pip install git+https://github.com/xXLODXx/hermes-skill-router.git
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

## Learning (legacy v1) and context rescue (v2)

**Status note (v0.800):** the live v2 runtime does **not** learn. The bounded
session context (last tool results + assistant reply) is kept in RAM for
**context rescue** and expires with the session TTL. The learning paths below
belong to the legacy v1 engine; the dashboard still visualizes existing
`learned_keywords.json` / `tool_stats.json` files when present.

The legacy engine could additionally learn from two *follow-signal* sources:

- `post_tool_call`: technical keywords from tool results (e.g. a Kanban task
  body) are associated with the skill that produced them — resolves indirect
  tasks like *"check the kanban board and work through the tasks"*, where the
  actual task lives in the tool result, not the user message.
- `post_llm_call`: technical keywords from the assistant's reply reinforce the
  skills already associated with this task's user words — resolves
  *"yes, option A"* confirmations, where the real content is in the LLM output.

In the legacy engine this was enabled by default since 2026-08-13 (result
learning is what gives ALL skills causal word chips). In the v2 runtime the
equivalent switch is `SKILL_ROUTER_V2_OUTPUT_LEARNING` (default off; the
buffering itself stays available for context rescue). Disable the legacy
path with:

```yaml
# config.yaml
skill_router:
  output_learning: false
```

Both sources are hardened: field whitelist (`body`, `output`, `text`,
`description`, `result`, `summary`), 500-char cap per field, failed tool
statuses ignored, IDs/hashes never learned, and nothing is learned without an
existing causal association (lift gate). In v2 the same bounded context
(last 2 tool results, 500 chars each, plus ≤800 chars of the last reply) feeds
context rescue instead — only when the turn would otherwise match nothing.

## Stopword strategy (static + dynamic + skill-selectivity)

- A small static, language-neutral base set filters universal filler words
  (`the`, `und`, `task`, `app`, …).
- **Dynamic document-frequency generics** (Schritt 7): any word that describes
  ≥ 40 % of all installed skills (tags + name + category + description) is
  treated as generic — it no longer distinguishes anything. This is
  **language-independent** (pure statistics, no dictionary) and
  **self-maintaining** (adapts to your skill collection). Threshold:
  `GENERIC_DF_RATIO` in `skill_router/engine.py`.
- **Skill-selectivity noise suppression** (2026-08-22): The two signals above
  still let words through that appear in tasks but are bound to *base workflow
  tools* (`terminal`, `process`, `read_file`, … — the channel with thousands
  of calls). Such words (`wars`→terminal, `router`→terminal, `kann`/`weis`)
  are **not skill signals** and used to pollute matching and clusters. The
  router now decides **self-learning, dictionary-free**: a word is a routing
  signal iff its strongest association target is an *installed skill* **and**
  its skill-selectivity (share of association counts on skills) ≥
  `SKILL_SELECTIVITY_THRESHOLD` (0.5). Calibrated on real data (19 clean
  signals, 0 noise leaks). It is applied at three points:
  1. **Matching** (`build_injection`): noise words add no weight.
  2. **Prune** (`prune_lexicon(..., skill_names=...)`): noise words bound only
     to base tools are physically removed from the lexicon.
  3. The classifier is recomputed per run from the installed skill set, so it
     adapts automatically as skills are added or removed.

## Development

```bash
pip install -e .[dev]
pytest
```

Tests build a temporary `HERMES_HOME` with fixture skills and verify matching,
matrix parsing, learning and topic-change behavior end-to-end.

## License

MIT
