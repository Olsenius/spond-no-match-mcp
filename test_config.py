"""Tests for settings and the gateway's /config contract, with synthetic data."""

import json
import stat

import pytest

from settings import Settings, parse_kids

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def fields(doc: dict) -> dict:
    return {f["key"]: f for f in doc["fields"]}


class TestSettings:
    def test_env_wins_and_is_locked(self, tmp_path):
        (tmp_path / "settings.json").write_text(json.dumps({"SPOND_USERNAME": "stored@example.com"}))
        s = Settings({"DATA_DIR": str(tmp_path), "SPOND_USERNAME": "env@example.com"})
        assert s.username == "env@example.com"
        assert s.locked("SPOND_USERNAME")
        with pytest.raises(ValueError, match="environment variable"):
            s.update({"SPOND_USERNAME": "x@example.com"}, [])

    def test_empty_env_is_not_locked(self):
        s = Settings({"DATA_DIR": "", "KIDS_CONFIG": ""})
        assert not s.locked("KIDS_CONFIG")

    def test_saved_with_mode_0600(self, tmp_path):
        s = Settings({"DATA_DIR": str(tmp_path)})
        s.update({"SPOND_USERNAME": "user@example.com", "SPOND_PASSWORD": "synthetic"}, [])
        path = tmp_path / "settings.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert Settings({"DATA_DIR": str(tmp_path)}).configured

    def test_empty_secret_keeps_current(self, tmp_path):
        s = Settings({"DATA_DIR": str(tmp_path)})
        s.update({"SPOND_PASSWORD": "synthetic"}, [])
        s.update({"SPOND_PASSWORD": ""}, [])
        assert s.password == "synthetic"

    def test_clear(self, tmp_path):
        s = Settings({"DATA_DIR": str(tmp_path)})
        s.update({"KIDS_CONFIG": "Emma"}, [])
        s.update({}, ["KIDS_CONFIG"])
        assert s.kids == []

    def test_validates_before_storing(self, tmp_path):
        s = Settings({"DATA_DIR": str(tmp_path)})
        with pytest.raises(ValueError, match="boolean"):
            s.update({"SPOND_USERNAME": "user@example.com", "MCP_READ_ONLY": "kanskje"}, [])
        assert s.username == ""
        assert not (tmp_path / "settings.json").exists()

    def test_unknown_key(self):
        with pytest.raises(ValueError, match="unknown setting"):
            Settings({"DATA_DIR": ""}).update({"MCP_AUTH_TOKEN": "x"}, [])

    def test_invalid_env_fails_at_startup(self):
        with pytest.raises(ValueError, match="MCP_READ_ONLY must be a boolean"):
            Settings({"DATA_DIR": "", "MCP_READ_ONLY": "kanskje"})

    def test_memory_only_without_data_dir(self, tmp_path):
        s = Settings({"DATA_DIR": str(tmp_path / "missing")})
        s.update({"SPOND_USERNAME": "user@example.com"}, [])
        assert s.username == "user@example.com"
        assert not (tmp_path / "missing").exists()

    def test_corrupt_file_is_ignored(self, tmp_path):
        (tmp_path / "settings.json").write_text("{not json")
        assert Settings({"DATA_DIR": str(tmp_path)}).username == ""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("", []),
            ("Astrid, Arvid", ["Astrid", "Arvid"]),
            ('["Emma"]', ["Emma"]),
            ('[{"name": "Oliver", "groups": ["x"]}]', ["Oliver"]),
        ],
    )
    def test_parse_kids(self, value, expected):
        assert parse_kids(value) == expected

    def test_parse_kids_rejects_bad_json(self):
        with pytest.raises(ValueError, match="KIDS_CONFIG"):
            parse_kids("[oops")

    def test_doc_never_returns_secret(self):
        s = Settings({"DATA_DIR": "", "SPOND_USERNAME": "user@example.com", "SPOND_PASSWORD": "synthetic"})
        doc = s.doc()
        assert "synthetic" not in json.dumps(doc)
        f = fields(doc)
        assert f["SPOND_PASSWORD"] == {**f["SPOND_PASSWORD"], "value": "", "set": True, "locked": True}
        assert f["SPOND_USERNAME"]["value"] == "user@example.com"
        assert f["MCP_READ_ONLY"]["value"] == "false"
        assert doc["name"] == "spond-mcp" and doc["configured"] is True


class TestConfigAPI:
    @pytest.fixture
    def client(self, make_client, tmp_path):
        with make_client(TOKEN, {"DATA_DIR": str(tmp_path)}) as c:
            yield c

    def test_requires_token(self, client):
        assert client.get("/config").status_code == 401
        assert client.get("/config", headers={"Authorization": "Bearer wrong"}).status_code == 401

    def test_separate_config_token(self, make_client):
        with make_client(TOKEN, config_token="config-token") as c:
            assert c.get("/config", headers=AUTH).status_code == 401
            assert c.get("/config", headers={"Authorization": "Bearer config-token"}).status_code == 200
            assert c.get("/healthz?check=1", headers={"Authorization": "Bearer config-token"}).status_code == 503

    def test_off_without_any_token(self, make_client):
        with make_client("") as c:
            assert c.get("/config").status_code == 404
            assert c.post("/config", json={"values": {"SPOND_USERNAME": "x"}}).status_code == 404

    def test_get_schema(self, client):
        resp = client.get("/config", headers=AUTH)
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        doc = resp.json()
        assert doc["configured"] is False
        assert [f["key"] for f in doc["fields"]] == ["SPOND_USERNAME", "SPOND_PASSWORD", "KIDS_CONFIG", "MCP_READ_ONLY"]
        assert {f["type"] for f in doc["fields"]} <= {"text", "url", "secret", "bool", "select"}

    def test_post_saves_and_applies_without_restart(self, client, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        import main

        old = MagicMock(close=AsyncMock())
        monkeypatch.setattr(main, "service", old)
        body = {
            "values": {"SPOND_USERNAME": "user@example.com", "SPOND_PASSWORD": "synthetic", "MCP_READ_ONLY": "true"}
        }
        resp = client.post("/config", json=body, headers=AUTH)
        assert resp.status_code == 200
        assert "synthetic" not in resp.text
        assert resp.json()["configured"] is True
        # The old client is closed; the next call logs in with the new account.
        old.close.assert_awaited_once()
        assert main.service is None
        stored = json.loads((tmp_path / "settings.json").read_text())
        assert stored["SPOND_USERNAME"] == "user@example.com"
        # Read-only applies at once.
        tools = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={**AUTH, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        ).json()["result"]["tools"]
        assert "respond_to_event" not in {t["name"] for t in tools}

    def test_post_errors(self, client):
        assert client.post("/config", content=b"{oops", headers=AUTH).status_code == 400
        resp = client.post("/config", json={"values": {"MCP_READ_ONLY": "kanskje"}}, headers=AUTH)
        assert resp.status_code == 400
        assert "boolean" in resp.json()["error"]
        resp = client.post("/config", content=b"x" * (64 * 1024 + 1), headers=AUTH)
        assert resp.status_code == 413

    def test_locked_by_env(self, make_client, tmp_path):
        env = {"DATA_DIR": str(tmp_path), "SPOND_PASSWORD": "synthetic"}
        with make_client(TOKEN, env) as c:
            resp = c.post("/config", json={"values": {"SPOND_PASSWORD": "other"}}, headers=AUTH)
            assert resp.status_code == 400
            assert "environment variable" in resp.json()["error"]
            assert fields(c.get("/config", headers=AUTH).json())["SPOND_PASSWORD"]["locked"] is True

    def test_logs_no_values(self, client, caplog):
        client.post("/config", json={"values": {"SPOND_USERNAME": "user@example.com"}}, headers=AUTH)
        assert "user@example.com" not in caplog.text
