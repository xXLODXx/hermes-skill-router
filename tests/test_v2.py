"""V2 contract tests: evidence, session isolation and fail-safe behavior."""

import json
from pathlib import Path

from skill_router.v2.audit import record
from skill_router.v2.catalog import scan_catalog
from skill_router.v2.models import Evidence, RoutingDecision, SkillRecord
from skill_router.v2.render import render
from skill_router.v2.selector import select
from skill_router.v2.session import SessionStore


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


def test_render_contains_reasoned_candidates(tmp_path: Path) -> None:
    decision = select("extract PDF OCR", scan_catalog(_skills(tmp_path)))
    output = render(decision)
    assert output is not None
    assert "pdf-extraction" in output
    assert "evidence:" in output


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


def test_hook_persists_external_loaded_skills(monkeypatch, tmp_path: Path) -> None:
    """A loader-provided skill must remain excluded on the next turn."""
    import skill_router

    class Context:
        def __init__(self) -> None:
            self.hooks = {}

        def register_hook(self, name: str, callback) -> None:
            self.hooks[name] = callback

    monkeypatch.setattr(skill_router.engine, "hermes_home", lambda: tmp_path)
    _skills(tmp_path)
    context = Context()
    skill_router.register(context)
    inject = context.hooks["pre_llm_call"]
    assert inject("prüfe Android emulator", "session-loaded", loaded_skills=["android-emulator"]) is None
    state = skill_router._STORE.get("session-loaded")
    assert state is not None
    assert "android-emulator" in state.already_loaded
    assert context.hooks["post_tool_call"]() is None
    assert context.hooks["post_llm_call"]() is None


def test_candidate_budget_is_hard_capped() -> None:
    skills = [
        SkillRecord(f"skill-{index}", "test", tags=("shared", "task"))
        for index in range(8)
    ]
    decision = select("shared task", skills)
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
    evidence = skill_router._matrix_evidence("bitte skill-audit durchführen")
    assert evidence["skill-artifact-validation"][0].kind == "matrix"
    assert evidence["skill-artifact-validation"][0].detail == "Matrix: Pflicht"


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
