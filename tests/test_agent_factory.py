import json
import pytest
from pathlib import Path
pytestmark = pytest.mark.unit


def _write_spec(tmp_path: Path, content: str, name: str = "test_agent.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


class TestLoadSpec:
    def test_valid_spec(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, """
id: test_agent
name: Test Agent
role: Test Role
persona: A test persona for unit tests.
llm_tier: analysis
""")
        spec = load_spec(p)
        assert spec["id"] == "test_agent"
        assert spec["llm_tier"] == "analysis"

    def test_missing_required_field_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, "id: test\nname: Test\n")
        with pytest.raises(ValueError, match="missing required field"):
            load_spec(p)

    def test_invalid_llm_tier_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, "id: t\nname: T\nrole: R\npersona: P\nllm_tier: superfast\n")
        with pytest.raises(ValueError, match="llm_tier"):
            load_spec(p)


class TestScanRegistry:
    def test_empty_dir(self, tmp_path):
        from agents.agent_factory import scan_registry
        result = scan_registry(tmp_path)
        assert result == []

    def test_skips_schema_file(self, tmp_path):
        from agents.agent_factory import scan_registry
        _write_spec(tmp_path, "skip: true", "_schema.yaml")
        result = scan_registry(tmp_path)
        assert result == []

    def test_loads_valid_spec(self, tmp_path):
        from agents.agent_factory import scan_registry
        _write_spec(tmp_path, "id: x\nname: X\nrole: R\npersona: P\nllm_tier: light\n")
        result = scan_registry(tmp_path)
        assert len(result) == 1
        assert result[0]["id"] == "x"

    def test_skips_invalid_spec_logs_warning(self, tmp_path):
        from agents.agent_factory import scan_registry
        _write_spec(tmp_path, "id: bad\n")
        result = scan_registry(tmp_path)
        assert result == []

    def test_nonexistent_dir_returns_empty(self):
        from agents.agent_factory import scan_registry
        result = scan_registry(Path("/nonexistent/registry"))
        assert result == []

    def test_non_directory_path_returns_empty(self, tmp_path):
        from agents.agent_factory import scan_registry
        f = tmp_path / "not_a_dir.yaml"
        f.write_text("x: 1")
        result = scan_registry(f)
        assert result == []

    def test_empty_yaml_file_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, "", "empty.yaml")
        with pytest.raises(ValueError, match="empty"):
            load_spec(p)

    def test_non_dict_yaml_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, "42", "scalar.yaml")
        with pytest.raises(ValueError, match="must be a dict"):
            load_spec(p)

    def test_field_type_validation_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, """
id: t\nname: T\nrole: R\npersona: P\nllm_tier: analysis\ntools: "not-a-list"\n""")
        with pytest.raises(ValueError, match="'tools' must be a list"):
            load_spec(p)

    def test_market_type_validation_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, """
id: t\nname: T\nrole: R\npersona: P\nllm_tier: analysis\nmarkets: "not-a-list"\n""")
        with pytest.raises(ValueError, match="'markets' must be a list"):
            load_spec(p)

    def test_non_string_required_field_raises(self, tmp_path):
        from agents.agent_factory import load_spec
        p = _write_spec(tmp_path, "id: t\nname: T\nrole: R\npersona: P\nllm_tier: analysis\nmax_iter: five\n")
        spec = load_spec(p)
        assert spec["max_iter"] == "five"


class TestCreateAgentFromYaml:
    def test_valid_yaml(self):
        from agents.agent_factory import create_agent_from_yaml
        spec = create_agent_from_yaml("""
id: test_agent
name: Test
role: Analyst
persona: A test agent
llm_tier: analysis
""")
        assert spec["id"] == "test_agent"

    def test_empty_yaml_raises(self):
        from agents.agent_factory import create_agent_from_yaml
        with pytest.raises(ValueError, match="Empty"):
            create_agent_from_yaml("")

    def test_non_dict_yaml_raises(self):
        from agents.agent_factory import create_agent_from_yaml
        with pytest.raises(ValueError, match="must define a mapping"):
            create_agent_from_yaml("42")

    def test_missing_field_raises(self):
        from agents.agent_factory import create_agent_from_yaml
        with pytest.raises(ValueError, match="Missing required field"):
            create_agent_from_yaml("id: t\nname: T\n")

    def test_invalid_tier_raises(self):
        from agents.agent_factory import create_agent_from_yaml
        with pytest.raises(ValueError, match="llm_tier"):
            create_agent_from_yaml("id: t\nname: T\nrole: R\npersona: P\nllm_tier: turbo\n")


class TestBuildAgentFromSpec:
    def test_missing_tools_defaults_to_empty(self):
        from agents.agent_factory import build_agent_from_spec
        agent = build_agent_from_spec({"id": "t", "name": "T", "role": "R", "persona": "P", "llm_tier": "light", "max_iter": 2})
        assert agent.role == "R"
        assert agent.max_iter == 2

    def test_memory_context_injected(self):
        from agents.agent_factory import build_agent_from_spec
        agent = build_agent_from_spec({"id": "t", "name": "T", "role": "R", "persona": "Base persona.", "llm_tier": "light", "memory_context": "yelahanka", "tools": []})
        assert "FOCUS MARKET: YELAHANKA" in agent.backstory

    def test_markets_used_when_no_memory_context(self):
        from agents.agent_factory import build_agent_from_spec
        agent = build_agent_from_spec({"id": "t", "name": "T", "role": "R", "persona": "Base persona.", "llm_tier": "light", "markets": ["Yelahanka"], "tools": []})
        assert "FOCUS MARKETS: Yelahanka" in agent.backstory