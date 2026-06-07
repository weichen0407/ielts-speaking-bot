import json
from pathlib import Path

from scripts.data_lifecycle import export_wiki, reset_dev_data


def test_reset_dev_data_keeps_user_memory_by_default(tmp_path: Path) -> None:
    (tmp_path / "monitor").mkdir()
    (tmp_path / "monitor" / "processor_runs.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "persona" / "processor" / "freechat").mkdir(parents=True)
    (tmp_path / "persona" / "processor" / "freechat" / "vocab.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "persona" / "memory").mkdir(parents=True)
    (tmp_path / "persona" / "memory" / "MEMORY.md").write_text("real memory", encoding="utf-8")
    (tmp_path / "persona" / "wiki" / "wiki").mkdir(parents=True)
    (tmp_path / "persona" / "wiki" / "wiki" / "source.md").write_text("---\n---\n", encoding="utf-8")

    result = reset_dev_data(tmp_path, clear_monitor=True, clear_processors=True)

    assert "monitor" in result["removed"]
    assert "persona/processor" in result["removed"]
    assert not (tmp_path / "monitor").exists()
    assert not (tmp_path / "persona" / "processor").exists()
    assert (tmp_path / "persona" / "memory" / "MEMORY.md").exists()
    assert (tmp_path / "persona" / "wiki" / "wiki" / "source.md").exists()


def test_export_wiki_copies_pages_raw_and_manifest(tmp_path: Path) -> None:
    (tmp_path / "persona" / "wiki" / "wiki").mkdir(parents=True)
    (tmp_path / "persona" / "wiki" / "raw").mkdir(parents=True)
    (tmp_path / "persona" / "wiki" / "wiki" / "source.md").write_text("page", encoding="utf-8")
    (tmp_path / "persona" / "wiki" / "raw" / "source.jsonl").write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "exports"

    result = export_wiki(tmp_path, output_dir)

    target = Path(result["output"])
    assert (target / "persona" / "wiki" / "wiki" / "source.md").read_text(encoding="utf-8") == "page"
    assert (target / "persona" / "wiki" / "raw" / "source.jsonl").exists()
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "wiki"
    assert "persona/wiki/wiki" in manifest["copied"]
