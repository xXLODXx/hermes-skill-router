"""V2 contract tests: evidence, session isolation and fail-safe behavior."""

import json
from pathlib import Path

from skill_router.v2.audit import record
from skill_router.v2.catalog import scan_catalog
from skill_router.v2.models import Evidence, RoutingDecision, SkillRecord
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
