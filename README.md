# Hermes Skill Router

[![CI](https://github.com/xXLODXx/hermes-skill-router/actions/workflows/ci.yml/badge.svg)](https://github.com/xXLODXx/hermes-skill-router/actions/workflows/ci.yml)

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that makes skill
discovery **task-aware and self-learning**. It injects a compact, relevance-filtered
list of routing topics and skills into the first turn of every session — so the
model no longer has to scan the full skill index and guess.

```
### Skill Routing (automatic, task-based)
Matched topics:
- Documents / OCR (Match 1)
  Required: pdf-extraction, action-items
  Optional: debugging
Suggested skills (not routed by matrix):
- productivity/calendar-sync [Calendar, Schedule]
Load matching skills with skill_view(name) and follow their instructions.
```

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
   No match → a single short fallback hint per session.
3. **Usage learning** — every tool start (`pre_tool_call`) associates the
   current task's keywords with the tool that was actually used (skill_view
   calls map to the loaded skill). The matcher grows with your real usage
   patterns — no manual maintenance.
4. **Causal weighting & self-cleaning** — raw co-occurrence counts are gated by
   a lift measure (observed / expected-by-chance). Words that appear before
   every tool (e.g. "bitte", "schnell") get lift ~1 and weight nothing; words
   that reliably precede one tool (e.g. "emulator" → adb tools) get weight.
   The lexicon is pruned on every save: entries without any causal association
   are removed. Marginal counts live in `tool_stats.json`.

Typical cost: **70–200 tokens per injection**, 0 tokens for follow-ups on the
same topic.

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

Restart Hermes (CLI/TUI/desktop) — plugins load at process start.

## Configuration

| Setting | Default | Description |
|---|---|---|
| `SKILL_ROUTER_MATRIX_PATH` (env) | unset | Optional path to a routing-matrix markdown file (see format below). Without it, the plugin works purely on tag/description matching. |
| `HERMES_HOME` (env) | `~/.hermes` | Where skills live. |

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

## Output learning (post_tool_call / post_llm_call) — opt-in

By default the router learns only from the raw user message (decision phase).
Two additional *follow-signal* sources are available behind a feature flag:

- `post_tool_call`: technical keywords from tool results (e.g. a Kanban task
  body) are associated with the skill that produced them — resolves indirect
  tasks like *"check the kanban board and work through the tasks"*, where the
  actual task lives in the tool result, not the user message.
- `post_llm_call`: technical keywords from the assistant's reply reinforce the
  skills already associated with this task's user words — resolves
  *"yes, option A"* confirmations, where the real content is in the LLM output.

Enabled by default since 2026-08-13 (after field observation — result
learning is what gives ALL skills causal word chips, not only the words
that happen to appear in the user message). Explicitly disable it with:

```yaml
# config.yaml
skill_router:
  output_learning: false
```

Both sources are hardened: field whitelist (`body`, `output`, `text`,
`description`, `result`, `summary`), 500-char cap per field, failed tool
statuses ignored, IDs/hashes never learned, and nothing is learned without an
existing causal association (lift gate). The last 3 tool results and the last
assistant reply also enrich follow-up injections in the same session.

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
