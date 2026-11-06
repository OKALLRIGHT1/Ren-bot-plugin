import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_market_entries_match_plugin_versions():
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    for name in ("code_agent", "mcp_tools"):
        entries = [row for row in index["plugins"] if row["id"] == name]
        assert len(entries) == 1
        config = json.loads((ROOT / name / "config.json").read_text(encoding="utf-8"))
        assert entries[0]["version"] == config["version"]
        assert entries[0]["trigger"] == config["trigger"]
        assert (ROOT / name / "README.md").is_file()


def test_mcp_implementation_has_no_dependency_on_host_mcp():
    for path in (ROOT / "mcp_tools").glob("*.py"):
        assert "integrations.mcp" not in path.read_text(encoding="utf-8")
