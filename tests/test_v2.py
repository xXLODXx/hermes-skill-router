"""V2 contract tests: evidence, session isolation and fail-safe behavior."""

from pathlib import Path

from skill_router.v2.audit import record
from skill_router.v2.catalog import scan_catalog
from skill_router.v2.models import RoutingDecision
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
