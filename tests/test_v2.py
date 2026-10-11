"""V2 contract tests: evidence, session isolation and fail-safe behavior."""

import json
import os
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from skill_router.v2.audit import record
from skill_router.v2.catalog import scan_catalog
from skill_router.v2.models import (
    CandidateDecision,
    Evidence,
    RoutingDecision,
    SkillRecord,
)
from skill_router.v2.render import FALLBACK, render
from skill_router.v2.selector import select
from skill_router.v2.session import SessionStore


class _FakeContext:
    """Minimal hook registry: name -> callback."""

    def __init__(self) -> None:
        self.hooks: dict = {}

    def register_hook(self, name: str, callback) -> None:
        self.hooks[name] = callback


def _skills(tmp_path: Path) -> Path:
    root = tmp_path / "skills" / "software-development"
    for name, tags, desc in [
        ("android-emulator", "Android, UI, emulator", "Test Android emulator keyboard and tap behavior."),
        ("pdf-extraction", "PDF, OCR, documents", "Extract text from PDF documents."),
    ]:
        path = root / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\nmetadata:\n  hermes:\n    tags: [{tags}]\n---\n",
            encoding="utf-8",
        )
    return tmp_path / "skills"


def _registered(monkeypatch, tmp_path: Path) -> _FakeContext:
    """Register the plugin against a temp home with isolated audit output."""
    import skill_router

    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)
    monkeypatch.setattr(skill_router, "_audit_path", lambda: tmp_path / "data" / "audit.jsonl")
    _skills(tmp_path)
    context = _FakeContext()
    skill_router.register(context)
    return context


def test_catalog_and_required_evidence(tmp_path: Path) -> None:
    catalog = scan_catalog(_skills(tmp_path))
    decision = select("prüfe Android emulator keyboard", catalog)
    assert [item.skill.name for item in decision.candidates] == ["android-emulator"]
    assert decision.candidates[0].decision == "required"
    assert "tag" in {item.kind for item in decision.candidates[0].evidence}


def test_already_loaded_is_rejected_and_unknown_task_is_safe(tmp_path: Path) -> None:
    catalog = scan_catalog(_skills(tmp_path))
    loaded = select("prüfe Android emulator", catalog, already_loaded=["android-emulator"])
    assert not loaded.candidates
    assert loaded.fallback_reason == "no_high_confidence_match"
    assert select("erzähle einen Witz", catalog).candidates == ()


def test_session_store_isolation() -> None:
    store = SessionStore(ttl_seconds=60)
    store.begin("a", "android")
    store.begin("b", "pdf")
    store.update("a", injected={"android-emulator"})
    first = store.get("a")
    second = store.get("b")
    assert first is not None and second is not None
    assert first.injected == {"android-emulator"}
    assert second.injected == set()
    assert store.size() == 2


def test_render_is_compact_but_keeps_reasons(tmp_path: Path) -> None:
    decision = select("extract PDF OCR", scan_catalog(_skills(tmp_path)))
    output = render(decision)
    assert output is not None
    assert output.splitlines()[0] == "## Skill Router v2"
    assert "pdf-extraction" in output
    # Kompaktformat: keine Label-Wörter, aber Evidenzarten bleiben sichtbar.
    assert "confidence" not in output
    assert "evidence:" not in output
    assert "(" in output and ")" in output


def test_confidence_is_monotonic_and_exposes_raw_scores_above_the_old_ceiling() -> None:
    """High-scoring candidates must remain distinguishable to consumers."""
    skills = [
        SkillRecord("codex", "test", tags=("refactor", "module", "analysis"), description="review"),
        SkillRecord("automation", "test", tags=("codex", "refactor", "module"), description="review"),
    ]

    decision = select("codex refactor module analysis review", skills)

    assert [item.skill.name for item in decision.candidates] == ["codex", "automation"]
    first, second = decision.candidates
    assert first.score == 15.0
    assert second.score == 10.0
    assert first.exact_score == first.score
    assert second.exact_score == second.score
    assert 0.0 < second.confidence < first.confidence < 1.0


def test_confidence_preserves_the_cross_kind_corroboration_bonus() -> None:
    """Corroborating fields must still outrank an otherwise higher single-field score."""
    skills = [
        SkillRecord("single-field", "test", tags=("alpha", "beta", "gamma")),
        SkillRecord("delta", "test", tags=("alpha",)),
    ]

    decision = select("alpha beta gamma delta", skills)

    assert [item.skill.name for item in decision.candidates] == ["delta", "single-field"]
    assert decision.candidates[0].score == 8.0
    assert decision.candidates[1].score == 9.0
    assert decision.candidates[0].confidence > decision.candidates[1].confidence


def test_native_plugin_layout_has_no_runtime_python_project() -> None:
    """Dependency-free directory plugins must not enter Hermes PM workspaces."""
    root = Path(__file__).resolve().parent.parent
    assert (root / "plugin.yaml").is_file()
    assert not (root / "pyproject.toml").exists()
    assert {"fastapi", "mypy", "pytest", "ruff"} <= set(
        (root / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    )
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip install -r requirements-dev.txt" in workflow
    assert "PYTHONPATH=. pytest -q" in workflow


def test_plugin_version_matches_manifest() -> None:
    from skill_router.version import plugin_version

    manifest = (Path(__file__).resolve().parent.parent / "plugin.yaml").read_text(encoding="utf-8")
    assert f'version: "{plugin_version()}"' in manifest


def test_audit_hashes_session_and_never_stores_raw_id(tmp_path: Path) -> None:
    path = tmp_path / "data" / "v2.jsonl"
    record(path, "t_private_session_123", RoutingDecision())
    text = path.read_text(encoding="utf-8")
    assert "t_private_session_123" not in text
    assert '"fallback_reason": null' in text
    event = json.loads(text)
    assert event["accepted_count"] == 0
    assert event["rejected_count"] == 0
    assert event["confidence_avg"] == 0.0
    assert event["score_avg"] == 0.0


def test_audit_event_is_enriched(tmp_path: Path) -> None:
    path = tmp_path / "data" / "v2.jsonl"
    record(
        path,
        "s-enriched",
        RoutingDecision(),
        catalog_size=42,
        profile="app",
        matrix_source="workflow-matrix.md",
        rescue=True,
        fallback_emitted=True,
        rendered_chars=123,
    )
    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["catalog_size"] == 42
    assert event["profile"] == "app"
    assert event["matrix_source"] == "workflow-matrix.md"
    assert event["rescue"] is True
    assert event["fallback_emitted"] is True
    assert event["rendered_chars"] == 123
    assert event["top_rejected"] == []
    assert event["score_max"] == 0.0
    assert event["score_min"] == 0.0
    assert isinstance(event["plugin_version"], str) and event["plugin_version"]


def test_audit_path_prefers_session_home_install(monkeypatch, tmp_path: Path) -> None:
    """Multi-profile hosts: records resolve to the session's own install."""
    import skill_router

    install = tmp_path / "plugins" / "skill-router"
    install.mkdir(parents=True)
    (install / "plugin.yaml").write_text('name: skill-router\nversion: "0"\n', encoding="utf-8")
    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)
    assert skill_router._audit_path() == install / "data" / "v2_injections.jsonl"


def test_audit_path_falls_back_without_profile_install(monkeypatch, tmp_path: Path) -> None:
    """A home without a skill-router install keeps the loaded copy's directory."""
    import skill_router

    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)
    assert skill_router._audit_path() == skill_router._PLUGIN_DIR / "data" / "v2_injections.jsonl"


def test_hook_records_into_session_home_install(monkeypatch, tmp_path: Path) -> None:
    """End-to-end: the hook's audit event lands in the session home's install."""
    import skill_router

    install = tmp_path / "plugins" / "skill-router"
    install.mkdir(parents=True)
    (install / "plugin.yaml").write_text('name: skill-router\nversion: "0"\n', encoding="utf-8")
    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)
    _skills(tmp_path)
    context = _FakeContext()
    skill_router.register(context)
    context.hooks["pre_llm_call"]("extract PDF OCR", "s-session-home")
    lines = (install / "data" / "v2_injections.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["catalog_size"] == 2


def test_hook_audit_records_compact_stage_status(monkeypatch, tmp_path: Path) -> None:
    """Audit stage status identifies where a routing decision was made."""
    context = _registered(monkeypatch, tmp_path)

    output = context.hooks["pre_llm_call"]("extract PDF OCR", "s-stage-status")

    assert output is not None
    event = json.loads((tmp_path / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert event["stages"] == {
        "catalog_available": True,
        "matrix_active": False,
        "matrix_skill_count": 0,
        "selector_candidate_count": 1,
        "candidate_context_emitted": True,
        "deduplicated": False,
    }


def test_hook_persists_external_loaded_skills(monkeypatch, tmp_path: Path) -> None:
    """A loader-provided skill must remain excluded on the next turn."""
    import skill_router

    context = _registered(monkeypatch, tmp_path)
    inject = context.hooks["pre_llm_call"]
    assert inject("prüfe Android emulator", "session-loaded", loaded_skills=["android-emulator"]) is None
    state = skill_router._STORE.get("session-loaded")
    assert state is not None
    assert "android-emulator" in state.already_loaded
    assert context.hooks["post_tool_call"]() is None
    assert context.hooks["post_llm_call"]() is None


def test_skill_is_loaded_only_after_successful_main_skill_view(monkeypatch, tmp_path: Path) -> None:
    """Denied calls and supporting-file reads must not suppress the next suggestion."""
    import skill_router

    context = _registered(monkeypatch, tmp_path)
    inject = context.hooks["pre_llm_call"]
    assert "pre_tool_call" not in context.hooks
    after = context.hooks["post_tool_call"]
    session = "s-view-outcome"
    assert inject("prüfe Android emulator", session) is not None
    args = {"name": "android-emulator"}
    after(tool_name="skill_view", session_id=session, args=args, status="error", result={"success": False})
    state = skill_router._STORE.get(session)
    assert state is not None and "android-emulator" not in state.already_loaded
    assert inject("prüfe Android emulator", session) is not None
    support = {"name": "android-emulator", "file_path": "references/details.md"}
    after(tool_name="skill_view", session_id=session, args=support, status="ok", result={"success": True})
    state = skill_router._STORE.get(session)
    assert state is not None and "android-emulator" not in state.already_loaded
    after(tool_name="skill_view", session_id=session, args=args, status="ok", result=json.dumps({"success": True}))
    state = skill_router._STORE.get(session)
    assert state is not None and "android-emulator" in state.already_loaded
    assert inject("prüfe Android emulator", session) is None


def test_parallel_successful_skill_views_accumulate_loaded_names(monkeypatch, tmp_path: Path) -> None:
    """One session can receive independent post-tool results concurrently."""
    import skill_router

    store = SessionStore()
    monkeypatch.setattr(skill_router, "_STORE", store)
    context = _registered(monkeypatch, tmp_path)
    session = "s-parallel-views"
    context.hooks["pre_llm_call"]("prüfe Android emulator und PDF OCR", session)
    barrier = threading.Barrier(2)
    original_get = store.get

    def synchronized_get(sid):
        snapshot = original_get(sid)
        if threading.current_thread() is not threading.main_thread():
            barrier.wait(timeout=5)
        return snapshot

    monkeypatch.setattr(store, "get", synchronized_get)
    after = context.hooks["post_tool_call"]

    def complete(name):
        after(tool_name="skill_view", session_id=session, args={"name": name}, status="ok",
              result=json.dumps({"success": True}))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(complete, ["android-emulator", "pdf-extraction"]))
    state = original_get(session)
    assert state is not None
    assert {"android-emulator", "pdf-extraction"} <= state.already_loaded


def test_fallback_hint_once_on_first_turn(monkeypatch, tmp_path: Path) -> None:
    context = _registered(monkeypatch, tmp_path)
    inject = context.hooks["pre_llm_call"]
    first = inject("erzähle einen Witz", "s-fallback", is_first_turn=True)
    assert first == {"context": FALLBACK}
    # Zweiter leerer Turn: kein erneuter Hinweis.
    assert inject("noch ein Witz", "s-fallback", is_first_turn=True) is None
    # Ohne Erst-Turn-Flag wird nie emititiert.
    assert inject("ein weiterer Witz", "s-fallback-2") is None


def test_context_rescue_uses_buffered_results(monkeypatch, tmp_path: Path) -> None:
    context = _registered(monkeypatch, tmp_path)
    inject = context.hooks["pre_llm_call"]
    tool_result = context.hooks["post_tool_call"]
    llm = context.hooks["post_llm_call"]
    assert inject("mach weiter", "s-rescue") is None
    tool_result(
        function_name="terminal",
        result={"output": "Android emulator keyboard check tap targets"},
        session_id="s-rescue",
    )
    llm(assistant_response="Der Android emulator braucht noch eine Keyboard-Prüfung.", session_id="s-rescue")
    out = inject("mach weiter", "s-rescue")
    assert out is not None
    assert "android-emulator" in out["context"]
    events = [
        json.loads(line)
        for line in (tmp_path / "data" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["rescue"] is True


def test_context_rescue_can_be_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SKILL_ROUTER_CONTEXT_RESCUE", "0")
    context = _registered(monkeypatch, tmp_path)
    inject = context.hooks["pre_llm_call"]
    tool_result = context.hooks["post_tool_call"]
    tool_result(function_name="terminal", result={"output": "Android emulator keyboard"}, session_id="s-off")
    assert inject("mach weiter", "s-off") is None


def test_catalog_cache_still_sees_edits(tmp_path: Path) -> None:
    skills = _skills(tmp_path)
    first = scan_catalog(skills)
    target = skills / "software-development" / "android-emulator" / "SKILL.md"
    assert first[0].description.startswith("Test Android")
    target.write_text(
        "---\nname: android-emulator\ndescription: Updated description of the emulator skill.\n"
        "metadata:\n  hermes:\n    tags: [Android]\n---\n",
        encoding="utf-8",
    )
    second = scan_catalog(skills)
    assert second[0].description.startswith("Updated")


def test_candidate_budget_is_hard_capped() -> None:
    """Eight passing candidates must be truncated to three (explicit name matches)."""
    skills = [SkillRecord(f"budget-{index}", "test") for index in range(8)]
    decision = select("budget", skills)
    assert len(decision.candidates) == 3
    assert len(decision.rejected) == 5
    assert all(item.reason == "Kandidatenbudget überschritten" for item in decision.rejected)


def test_required_matrix_overflow_is_visible_in_injected_context() -> None:
    """A bounded injection must not imply that the whole required pack was delivered."""
    skills = [SkillRecord(f"mandatory-{i}", "test") for i in range(7)]
    matrix = {skill.name: (Evidence("matrix", "pack", 6.0, "Matrix: Pflicht"),) for skill in skills}
    decision = select("neutral", skills, matrix=matrix)
    assert len(decision.candidates) == 6
    context = render(decision)
    assert context is not None
    assert "1 required matrix skill omitted" in context
    assert "mandatory-6" in context


def test_large_required_matrix_overflow_keeps_warning_bounded() -> None:
    skills = [SkillRecord(f"mandatory-{i}", "test") for i in range(20)]
    matrix = {skill.name: (Evidence("matrix", "pack", 6.0, "Matrix: Pflicht"),) for skill in skills}
    decision = select("neutral", skills, matrix=matrix)
    context = render(decision)
    assert context is not None
    assert "14 required matrix skills omitted" in context
    assert "+11 more" in context


def test_explicit_optional_matrix_overflow_is_not_called_required() -> None:
    skills = [SkillRecord(f"optional-{i}", "test") for i in range(7)]
    matrix = {skill.name: (Evidence("matrix", "pack", 4.0, "Matrix: Optional"),) for skill in skills}
    decision = select(" ".join(skill.name for skill in skills), skills, matrix=matrix)
    assert len(decision.candidates) == 6
    assert len([item for item in decision.rejected if "budget" in item.reason.casefold()]) == 1
    assert not any(item.reason == "Matrix-Pflichtbudget überschritten" for item in decision.rejected)
    assert "required matrix skill omitted" not in (render(decision) or "")


def test_common_catalog_words_alone_do_not_recommend_arbitrary_skills() -> None:
    skills = [SkillRecord(f"item-{i}", "test", tags=("commonword", "sharedword")) for i in range(12)]
    decision = select("commonword sharedword", skills)
    assert decision.candidates == ()
    assert decision.fallback_reason == "no_high_confidence_match"


def test_rare_corroborating_tag_remains_selectable() -> None:
    skills = [SkillRecord(f"item-{i}", "test", tags=("commonword", "sharedword")) for i in range(12)]
    skills[0] = SkillRecord("item-0", "test", tags=("commonword", "sharedword", "uniqueword"))
    decision = select("commonword sharedword uniqueword", skills)
    assert [item.skill.name for item in decision.candidates] == ["item-0"]


def test_language_neutral_stem_evidence() -> None:
    skill = SkillRecord("audio-processing", "media", tags=("convert", "audio"))
    decision = select("converting audio", [skill])
    assert [item.skill.name for item in decision.candidates] == ["audio-processing"]
    assert any(item.kind == "subword" for item in decision.candidates[0].evidence)


def test_language_neutral_compound_evidence() -> None:
    skill = SkillRecord("audio-processing", "media", tags=("audio",), description="Convert audio with FFmpeg")
    decision = select("Audiodatei FFmpeg", [skill])
    assert [item.skill.name for item in decision.candidates] == ["audio-processing"]
    assert any(item.kind == "subword" for item in decision.candidates[0].evidence)


def test_isolated_subword_signal_is_rejected() -> None:
    skill = SkillRecord("audio-processing", "media", tags=("convert",))
    decision = select("converting", [skill])
    assert not decision.candidates
    assert decision.rejected[0].reason == "isoliertes Stamm-/Teilwortsignal"


def _mass_tag_catalog(shared: int, tag: str = "commonword") -> list[SkillRecord]:
    return [SkillRecord(f"pkg-{index}", "test", tags=(tag,)) for index in range(shared)]


def test_generic_tag_word_cannot_trigger_alone() -> None:
    """A tag word shared catalog-wide is not a route trigger by itself."""
    decision = select("commonword", _mass_tag_catalog(12))
    assert not decision.candidates
    assert decision.fallback_reason == "no_high_confidence_match"
    assert all(item.reason == "generisches Signal (katalogweit häufig)" for item in decision.rejected)


def test_generic_tag_alone_does_not_consume_budget() -> None:
    """Mass matches must not push real candidates out of the discovery budget."""
    skills = _mass_tag_catalog(15) + [SkillRecord("specific", "test", tags=("commonword", "specialword"))]
    decision = select("commonword specialword", skills)
    assert [item.skill.name for item in decision.candidates] == ["specific"]
    assert not any(item.reason == "Kandidatenbudget überschritten" for item in decision.rejected)


def test_specific_tag_word_still_triggers() -> None:
    """A tag word carried by few skills keeps full weight (a single word suffices)."""
    skills = _mass_tag_catalog(10) + [SkillRecord("rare", "test", tags=("raretag",))]
    decision = select("raretag", skills)
    assert [item.skill.name for item in decision.candidates] == ["rare"]


def test_generic_tag_with_specific_description_still_passes() -> None:
    """Corroborating specific evidence rescues a generic tag match."""
    skill = SkillRecord(
        "guarded", "test", tags=("commonword",), description="Spezialisierte Prüfung von Randfällen"
    )
    decision = select("commonword spezialisierte randfällen", _mass_tag_catalog(12) + [skill])
    assert [item.skill.name for item in decision.candidates] == ["guarded"]


def test_matrix_required_skill_is_selected_even_without_name_tag_match() -> None:
    skill = SkillRecord("skill-artifact-validation", "software-development")
    decision = select(
        "prüfe den skill-router und führe einen skill-audit durch",
        [skill],
        matrix={
            "skill-artifact-validation": (
                Evidence("matrix", "Skill-Pflege / Curator-Update", 6.0, "Matrix: Pflicht"),
            )
        },
    )
    assert [item.skill.name for item in decision.candidates] == ["skill-artifact-validation"]
    assert decision.candidates[0].decision == "required"
    assert any(item.kind == "matrix" for item in decision.candidates[0].evidence)


def test_matrix_required_candidates_are_not_lost_to_discovery_budget() -> None:
    skills = [SkillRecord(f"required-{index}", "test") for index in range(4)]
    matrix = {
        skill.name: (Evidence("matrix", "Topic", 6.0, "Matrix: Pflicht"),)
        for skill in skills
    }
    decision = select("topic", skills, matrix=matrix)
    assert [item.skill.name for item in decision.candidates] == [f"required-{i}" for i in range(4)]


def test_hook_uses_profile_workflow_matrix(monkeypatch, tmp_path: Path) -> None:
    import skill_router

    matrix = tmp_path / "skills" / "software-development" / "workflow-router" / "references" / "workflow-matrix.md"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(
        "## Thema 1: Skill-Pflege\n\n**Keywords:** `skill-audit`, `curator`\n\n"
        "| Kategorie | Skills |\n|---|---|\n"
        "| **Pflicht** | `skill-artifact-validation` |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)
    evidence, source = skill_router._matrix_evidence("bitte skill-audit durchführen")
    assert evidence["skill-artifact-validation"][0].kind == "matrix"
    assert evidence["skill-artifact-validation"][0].detail == "Matrix: Pflicht"
    assert source == "workflow-matrix.md"


def test_matrix_keywords_require_token_boundaries(monkeypatch, tmp_path: Path) -> None:
    """A short keyword such as ``ui`` must not match inside ``Build``."""
    import skill_router

    matrix = tmp_path / "skills" / "software-development" / "workflow-router" / "references" / "workflow-matrix.md"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(
        "## Thema 1: Flutter UI\n\n**Keywords:** `ui`\n\n"
        "| Kategorie | Skills |\n|---|---|\n"
        "| **Pflicht** | `flutter-ui-vision-loop` |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)

    evidence, _ = skill_router._matrix_evidence("Build a Python CLI.")

    assert evidence == {}


def test_catalog_follows_profile_skill_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "default" / "software-development" / "linked-skill"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        "---\nname: linked-skill\ndescription: Follow symlinked skills.\n---\n",
        encoding="utf-8",
    )
    profile = tmp_path / "profile" / "skills" / "software-development"
    profile.mkdir(parents=True)
    (profile / "linked-skill").symlink_to(target, target_is_directory=True)
    assert [item.name for item in scan_catalog(tmp_path / "profile" / "skills")] == ["linked-skill"]


def test_tokens_returns_fresh_mutable_set() -> None:
    """The tokenizer cache must never leak a shared, mutable object."""
    from skill_router.v2 import evidence as evidence_mod

    first = evidence_mod.tokens("prüfe den emulator")
    assert "emulator" in first
    first.add("mutiert")
    assert "mutiert" not in evidence_mod.tokens("prüfe den emulator")


def test_catalog_walk_cache_respects_ttl(monkeypatch, tmp_path: Path) -> None:
    """Tree walk is TTL-cached; SKILL_ROUTER_SCAN_TTL=0 restores walk-per-call."""
    from skill_router.v2 import catalog as catalog_mod

    monkeypatch.delenv("SKILL_ROUTER_SCAN_TTL", raising=False)
    skills = _skills(tmp_path)
    assert len(catalog_mod.scan_catalog(skills)) == 2
    fresh = skills / "software-development" / "fresh-skill"
    fresh.mkdir(parents=True)
    (fresh / "SKILL.md").write_text(
        "---\nname: fresh-skill\ndescription: Neue Fähigkeit für Tests.\n---\n",
        encoding="utf-8",
    )
    # Innerhalb der TTL bleibt die gecachte Wege-Liste aktiv; Inhaltsänderungen
    # greifen sofort (stat), Neuzugänge erst nach dem nächsten Walk.
    assert len(catalog_mod.scan_catalog(skills)) == 2
    monkeypatch.setenv("SKILL_ROUTER_SCAN_TTL", "0")
    assert len(catalog_mod.scan_catalog(skills)) == 3


def test_matrix_requires_specific_signal_or_two_generic_signals(monkeypatch, tmp_path: Path) -> None:
    """A broad word such as review must not activate Flutter by itself."""
    import skill_router

    matrix = tmp_path / "skills" / "software-development" / "workflow-router" / "references" / "workflow-matrix.md"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(
        "## Thema 1: Flutter UI\n\n**Keywords:** `flutter`, `ui`, `review`\n\n"
        "| Kategorie | Skills |\n|---|---|\n"
        "| **Pflicht** | `flutter-ui-vision-loop` |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)

    broad_only, _ = skill_router._matrix_evidence("Bitte mache einen review des Pull Requests")
    specific, _ = skill_router._matrix_evidence("Bitte reviewe das Flutter UI")

    assert broad_only == {}
    assert "flutter-ui-vision-loop" in specific


def test_explicit_skill_mentions_expand_the_dynamic_budget() -> None:
    """Four named skills must not lose one merely because discovery defaults to three."""
    skills = [
        SkillRecord("routing-plugin-verification", "software-development"),
        SkillRecord("github", "software-development"),
        SkillRecord("plan", "software-development"),
        SkillRecord("hermes-plugin-release-rollout", "software-development"),
    ]

    decision = select(
        "Nutze routing-plugin-verification, github, plan und hermes-plugin-release-rollout.",
        skills,
    )

    assert {candidate.skill.name for candidate in decision.candidates} == {
        "routing-plugin-verification",
        "hermes-plugin-release-rollout",
        "github",
        "plan",
    }


def test_audit_records_priority_and_dynamic_budget(tmp_path: Path) -> None:
    """New tuning metrics remain aggregate-only and contain no session identifier."""
    path = tmp_path / "data" / "v2.jsonl"
    skill = SkillRecord("plan", "software-development")
    decision = RoutingDecision(
        candidates=(
            CandidateDecision(
                skill, "required", 0.9, (Evidence("name", "plan", 5.0, "Skillname enthält 'plan'"),)
            ),
        )
    )

    record(path, "private-session", decision, candidate_budget=4, explicit_skill_count=1)

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["candidate_budget"] == 4
    assert event["explicit_skill_count"] == 1
    assert "private-session" not in path.read_text(encoding="utf-8")


def test_subword_evidence_is_bounded_per_catalog_field() -> None:
    """Several morphological matches cannot multiply a candidate's support score."""
    skill = SkillRecord(
        "audio-processing",
        "media",
        description="Convert converted conversion audio files",
        tags=("convert",),
    )

    decision = select("converting conversion audio", [skill])

    candidate = decision.candidates[0]
    subwords = [item for item in candidate.evidence if item.kind == "subword"]
    assert len(subwords) <= 2


def test_negated_skill_name_is_not_explicit_or_selected() -> None:
    """A user who says not to create a plan must not receive the plan skill."""
    decision = select(
        "Bitte erstelle keinen Plan und nutze nicht plan.",
        [SkillRecord("plan", "software-development", tags=("planning",))],
    )

    assert decision.candidates == ()
    assert decision.explicit_skill_count == 0


def test_cached_catalog_is_shared_and_follows_added_skills(monkeypatch, tmp_path: Path) -> None:
    """A second process reads the shared cache instead of re-reading every SKILL.md."""
    from skill_router.v2 import catalog as catalog_mod

    monkeypatch.delenv("SKILL_ROUTER_SCAN_TTL", raising=False)
    skills, cache = _skills(tmp_path), tmp_path / "data" / "catalog-cache.json"
    first = catalog_mod.cached_catalog(skills, cache)
    assert first == scan_catalog(skills) and cache.is_file()
    scans: list[Path] = []
    monkeypatch.setattr(catalog_mod, "scan_catalog", lambda d: scans.append(d) or ())
    assert catalog_mod.cached_catalog(skills, cache) == first and not scans, "fresh cache is read"
    monkeypatch.setattr(catalog_mod, "scan_catalog", scan_catalog)
    folder = skills / "software-development"
    mtime = folder.stat().st_mtime_ns
    fresh = folder / "fresh-skill"
    fresh.mkdir()
    (fresh / "SKILL.md").write_text("---\nname: fresh-skill\n---\n", encoding="utf-8")
    os.utime(folder, ns=(mtime + 10**9, mtime + 10**9))  # coarse fs clocks may not tick within a test
    names = {r.name for r in catalog_mod.cached_catalog(skills, cache)}
    assert "fresh-skill" in names, "an added skill shows up on the next call, not after the walk TTL"
    stored = json.loads(cache.read_text(encoding="utf-8"))["records"]
    assert "fresh-skill" in {r["name"] for r in stored}, "and the shared cache carries it to other processes"


def test_cached_catalog_survives_a_dangling_skill_link(monkeypatch, tmp_path: Path) -> None:
    """A dangling junction or symlink in the skills root cannot be stat'ed; routing must not fail on it."""
    from skill_router.v2 import catalog as catalog_mod

    monkeypatch.delenv("SKILL_ROUTER_SCAN_TTL", raising=False)
    skills, cache = _skills(tmp_path), tmp_path / "data" / "catalog-cache.json"
    (skills / "dangling").mkdir()
    real_stat = os.stat

    def stat(path, *args, **kwargs):
        if os.fspath(path).endswith("dangling"):
            raise FileNotFoundError(2, "No such file or directory", os.fspath(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(catalog_mod.os, "stat", stat)
    assert catalog_mod.cached_catalog(skills, cache) == scan_catalog(skills)


def test_cached_catalog_treats_a_future_timestamp_as_stale(monkeypatch, tmp_path: Path) -> None:
    """A clock that moved back must not freeze the cache until it catches up."""
    from skill_router.v2 import catalog as catalog_mod

    monkeypatch.delenv("SKILL_ROUTER_SCAN_TTL", raising=False)
    skills, cache = _skills(tmp_path), tmp_path / "data" / "catalog-cache.json"
    catalog_mod.cached_catalog(skills, cache)
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["ts"] += 3600
    cache.write_text(json.dumps(data), encoding="utf-8")
    scans: list[Path] = []
    monkeypatch.setattr(catalog_mod, "scan_catalog", lambda d: scans.append(d) or ())
    catalog_mod.cached_catalog(skills, cache)
    assert scans, "a cache stamped in the future is rescanned"


def test_cached_catalog_serves_previous_scan_while_another_process_rescans(monkeypatch, tmp_path: Path) -> None:
    from skill_router.v2 import catalog as catalog_mod

    skills, cache = _skills(tmp_path), tmp_path / "data" / "catalog-cache.json"
    first = catalog_mod.cached_catalog(skills, cache)
    scans: list[Path] = []
    monkeypatch.setattr(catalog_mod, "scan_catalog", lambda d: scans.append(d) or ())
    monkeypatch.setattr(catalog_mod, "_scan_ttl", lambda: -1.0)  # cache always expired
    lock = cache.with_name(cache.name + ".lock")
    lock.write_text("", encoding="utf-8")
    assert catalog_mod.cached_catalog(skills, cache) == first and not scans
    assert lock.exists(), "the other process's lock is left alone"
    lock.unlink()
    catalog_mod.cached_catalog(skills, cache)
    assert scans and not lock.exists(), "without a lock this process rescans and releases its lock"


def test_cached_catalog_does_not_publish_without_lock_on_changed_tree(monkeypatch, tmp_path: Path) -> None:
    """An unlocked second scanner cannot replace the lock owner's future snapshot."""
    from skill_router.v2 import catalog as catalog_mod

    monkeypatch.delenv("SKILL_ROUTER_SCAN_TTL", raising=False)
    skills, cache = _skills(tmp_path), tmp_path / "data" / "catalog-cache.json"
    catalog_mod.cached_catalog(skills, cache)
    before = cache.read_bytes()
    lock = cache.with_name(cache.name + ".lock")
    lock.write_text("", encoding="utf-8")
    folder = skills / "software-development"
    new_skill = folder / "added-during-locked-scan"
    new_skill.mkdir()
    (new_skill / "SKILL.md").write_text("---\nname: added-during-locked-scan\n---\n", encoding="utf-8")
    result = catalog_mod.cached_catalog(skills, cache)
    assert "added-during-locked-scan" in {r.name for r in result}
    assert cache.read_bytes() == before, "only the owner of an existing lock may publish"
    assert lock.exists()


def test_cached_catalog_refreshes_nested_changes_on_ttl(monkeypatch, tmp_path: Path) -> None:
    """Nested categories are outside the cheap first-level signature, not permanent cache misses."""
    from skill_router.v2 import catalog as catalog_mod

    monkeypatch.setenv("SKILL_ROUTER_SCAN_TTL", "1")
    skills, cache = _skills(tmp_path), tmp_path / "data" / "catalog-cache.json"
    nested = skills / "software-development" / "subsection"
    nested.mkdir()
    catalog_mod.cached_catalog(skills, cache)
    added = nested / "nested-new"
    added.mkdir()
    (added / "SKILL.md").write_text("---\nname: nested-new\n---\n", encoding="utf-8")
    assert "nested-new" not in {r.name for r in catalog_mod.cached_catalog(skills, cache)}
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["ts"] -= 2
    cache.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(catalog_mod.time, "monotonic", lambda: 999999999.0)
    assert "nested-new" in {r.name for r in catalog_mod.cached_catalog(skills, cache)}


def test_cached_catalog_falls_back_when_signature_races_tree_change(monkeypatch, tmp_path: Path) -> None:
    from skill_router.v2 import catalog as catalog_mod

    skills, cache = _skills(tmp_path), tmp_path / "data" / "catalog-cache.json"
    monkeypatch.setattr(catalog_mod, "_signature", lambda _: (_ for _ in ()).throw(FileNotFoundError()))
    assert catalog_mod.cached_catalog(skills, cache) == scan_catalog(skills)


def test_catalog_never_routes_to_archived_or_backup_skills(tmp_path: Path) -> None:
    """The catalog must agree with Hermes: curator archives are not active skills."""
    from skill_router.v2 import catalog as catalog_mod

    skills = _skills(tmp_path)
    for hidden in (".archive", ".curator_backups", ".git"):
        archived = skills / hidden / "obsolete"
        archived.mkdir(parents=True)
        (archived / "SKILL.md").write_text("---\nname: obsolete\n---\n", encoding="utf-8")
    cache = tmp_path / "data" / "catalog-cache.json"
    assert {r.name for r in scan_catalog(skills)} == {"android-emulator", "pdf-extraction"}
    cached_names = {r.name for r in catalog_mod.cached_catalog(skills, cache)}
    assert cached_names == {"android-emulator", "pdf-extraction"}


def test_catalog_ignores_skills_inside_support_directories(tmp_path: Path) -> None:
    """References belonging to a skill are not independent Hermes skills."""
    skills = _skills(tmp_path)
    support = skills / "software-development" / "android-emulator" / "references" / "ghost"
    support.mkdir(parents=True)
    (support / "SKILL.md").write_text("---\nname: ghost\n---\n", encoding="utf-8")
    assert {r.name for r in scan_catalog(skills)} == {"android-emulator", "pdf-extraction"}


def test_host_visible_catalog_excludes_shadowed_and_includes_external(monkeypatch, tmp_path: Path) -> None:
    """Router suggestions must use the loadable names and sources Hermes resolves."""
    from skill_router.v2 import catalog as catalog_mod

    skills = _skills(tmp_path)
    external = tmp_path / "external"
    extra = external / "external-tool"
    extra.mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\nname: external-tool\nmetadata:\n  hermes:\n    tags: [outside]\n---\n", encoding="utf-8")
    rows = [
        {"path": skills / "software-development" / "android-emulator" / "SKILL.md", "root": skills,
         "category": "software-development", "load_name": None, "status": "shadowed"},
        {"path": extra / "SKILL.md", "root": external, "category": "external", "description": "Host-index description",
         "load_name": "external-tool",
         "status": "unique"},
    ]
    fake_tools = types.ModuleType("tools")
    fake_skills = types.ModuleType("tools.skills_tool")
    fake_skills.__dict__["_skill_catalog"] = lambda: rows
    monkeypatch.setitem(sys.modules, "tools", fake_tools)
    monkeypatch.setitem(sys.modules, "tools.skills_tool", fake_skills)
    found = catalog_mod.runtime_catalog(skills, tmp_path / "data" / "catalog-cache.json")
    assert [r.name for r in found] == ["external-tool"]
    assert found[0].source == str(extra / "SKILL.md")
    assert "outside" in found[0].tags
    assert found[0].description == "Host-index description"


def test_host_catalog_failure_does_not_recommend_unverified_local_skills(monkeypatch, tmp_path: Path) -> None:
    from skill_router.v2 import catalog as catalog_mod

    skills = _skills(tmp_path)
    fake_tools = types.ModuleType("tools")
    fake_skills = types.ModuleType("tools.skills_tool")

    def unavailable():
        raise RuntimeError("host index unavailable")

    fake_skills.__dict__["_skill_catalog"] = unavailable
    monkeypatch.setitem(sys.modules, "tools", fake_tools)
    monkeypatch.setitem(sys.modules, "tools.skills_tool", fake_skills)
    assert catalog_mod.runtime_catalog(skills, tmp_path / "data" / "catalog-cache.json") == ()


def test_broken_host_import_is_not_mistaken_for_standalone_mode(monkeypatch, tmp_path: Path) -> None:
    from skill_router.v2 import catalog as catalog_mod

    skills = _skills(tmp_path)

    def broken(_):
        raise ModuleNotFoundError("No module named 'host_dependency'", name="host_dependency")

    monkeypatch.setattr(catalog_mod.importlib, "import_module", broken)
    assert catalog_mod.runtime_catalog(skills, tmp_path / "data" / "catalog-cache.json") == ()


def test_missing_host_catalog_api_fails_closed(monkeypatch, tmp_path: Path) -> None:
    from skill_router.v2 import catalog as catalog_mod

    skills = _skills(tmp_path)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.skills_tool", types.ModuleType("tools.skills_tool"))
    assert catalog_mod.runtime_catalog(skills, tmp_path / "data" / "catalog-cache.json") == ()
