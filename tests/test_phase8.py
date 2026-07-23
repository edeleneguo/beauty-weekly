"""Phase 8 tests for independent page shells and one production entrypoint."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ("index.html", "fragrance.html")


def _load_pipeline_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_pipeline", ROOT / "build" / "validate_pipeline.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_independent_page_shells_exist():
    for name in OUTPUTS:
        assert (ROOT / "templates" / "pages" / name).is_file()


def test_renderer_uses_canonical_and_independent_shells():
    text = (ROOT / "build" / "render.py").read_text(encoding="utf-8")
    assert "CANONICAL_PATH" in text
    assert "PAGE_SHELL_DIR" in text
    assert "os.path.join(ROOT, template_name)" not in text


def test_pipeline_validator_passes():
    module = _load_pipeline_validator()
    assert module.validate_pipeline() == []


def test_legacy_tools_are_not_production_entrypoints():
    for name in ("extract_data.py", "fix_week28_data.py"):
        text = (ROOT / "build" / name).read_text(encoding="utf-8")
        assert "LEGACY ONE-TIME" in text
        assert "not a production pipeline entrypoint" in text
