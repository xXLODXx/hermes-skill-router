# Hermes Skill Router

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that makes skill
discovery **task-aware and self-learning**. It injects a compact, relevance-filtered
list of routing topics and skills into the first turn of every session — so the
model no longer has to scan the full skill index and guess.

```
### Skill-Routing (automatisch, aufgabenbasiert)
Erkannte Themen:
- Dokumenten-Analyse / PoC (Match 1)
  Pflicht: ocr-and-documents, document-to-action-items
  Optional: systematic-debugging, meeting-action-items
Lade passende Skills mit skill_view(name) und befolge deren Regeln.
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
3. **Self-learning** — when the model loads a skill that was *not* part of the
   injection (`on_skill_lifecycle` hook), the task's keywords are persistently
   associated with that skill. Next time, the skill is suggested automatically.
   The matcher grows with your real usage patterns — no manual maintenance.

Typical cost: **70–200 tokens per injection**, 0 tokens for follow-ups on the
same topic.

## Installation

### Via pip (recommended)

```bash
pip install git+https://github.com/<your-org>/hermes-skill-router.git
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

A markdown file with numbered topics, keyword lines and Pflicht/Optional
tables, e.g.:

```markdown
## Thema 1: Documents / OCR

**Keywords:** `ocr`, `pdf`, `document`, `scan`

| Kategorie | Skills |
|-----------|--------|
| **Pflicht** | `ocr-and-documents`, `document-to-action-items` |
| **Optional** | `systematic-debugging` |
```

Topics whose keywords match the task are injected with their Pflicht/Optional
skill lists; skills already routed by the matrix are not duplicated in the
auto-suggested section.

## Privacy

- The learned-association file (`learned_keywords.json`) is stored **locally** in
  the plugin directory and is **never transmitted anywhere**.
- It may contain keywords extracted from your own task messages; delete the file
  at any time to reset the learned associations.
- The plugin performs **no telemetry and no network calls**.

## Development

```bash
pip install -e .[dev]
pytest
```

Tests build a temporary `HERMES_HOME` with fixture skills and verify matching,
matrix parsing, learning and topic-change behavior end-to-end.

## License

MIT
