"""The remote backend: the provider must be a deployment decision, and a
failing model must never take the game down with it."""
import json
from hobbit.llm import LLMClient, LLMConfig, config_from_env


def test_env_config_is_absent_until_both_url_and_model_are_set():
    assert config_from_env({}) is None
    assert config_from_env({"HOBBIT_LLM_URL": "https://x/v1"}) is None
    assert config_from_env({"HOBBIT_LLM_MODEL": "m"}) is None


def test_env_config_infers_the_hosted_shape_from_a_key():
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.example/v1",
                           "HOBBIT_LLM_MODEL": "some-model",
                           "HOBBIT_LLM_KEY": "sk-test"})
    assert cfg.is_remote and cfg.api_key == "sk-test"
    assert cfg.base_url == "https://api.example/v1"  # trailing slash trimmed
    assert cfg.timeout <= 20  # a watching web player, not a terminal


def test_env_config_keeps_local_ollama_local():
    cfg = config_from_env({"HOBBIT_LLM_URL": "http://localhost:11434",
                           "HOBBIT_LLM_MODEL": "hermes3:8b"})
    assert not cfg.is_remote


def test_an_explicit_style_wins_over_the_guess():
    cfg = config_from_env({"HOBBIT_LLM_URL": "http://localhost:11434",
                           "HOBBIT_LLM_MODEL": "m",
                           "HOBBIT_LLM_STYLE": "openai"})
    assert cfg.is_remote


class _Fake(LLMClient):
    """Captures the request instead of making one."""
    def __init__(self, config, reply):
        super().__init__(config)
        self.sent = None
        self._reply = reply

    def _post(self, path, payload, timeout):
        self.sent = (path, payload, timeout)
        return self._reply


def test_remote_chat_speaks_openai_and_reads_its_reply():
    client = _Fake(LLMConfig(base_url="https://api.example/v1", model="m",
                             api_style="openai", api_key="sk-test"),
                   {"choices": [{"message": {"content": " Well met. "}}]})
    assert client.chat("sys", "usr") == "Well met."
    path, payload, _ = client.sent
    assert path == "/chat/completions"
    assert payload["messages"][0]["role"] == "system"
    assert "max_tokens" in payload and "options" not in payload


def test_local_chat_still_speaks_ollama():
    client = _Fake(LLMConfig(), {"message": {"content": "Aye."}})
    assert client.chat("sys", "usr") == "Aye."
    path, payload, _ = client.sent
    assert path == "/api/chat"
    assert payload["options"]["num_predict"] == 90  # ollama's spelling


def test_a_transport_failure_is_silent_and_falls_back():
    """The whole contract: a dead model must never raise into the game."""
    for cfg in (LLMConfig(), LLMConfig(api_style="openai", api_key="k")):
        client = _Fake(cfg, None)
        assert client.chat("sys", "usr") is None


def test_an_error_body_from_the_provider_is_not_mistaken_for_a_reply():
    """A 200 carrying {'error': ...} must read as failure, not as dialogue."""
    client = _Fake(LLMConfig(base_url="https://x/v1", model="m",
                             api_style="openai", api_key="k"),
                   {"error": {"message": "insufficient balance"}})
    assert client.chat("sys", "usr") is None


def test_an_empty_reply_is_a_failure_not_an_empty_line():
    client = _Fake(LLMConfig(base_url="https://x/v1", model="m",
                             api_style="openai", api_key="k"),
                   {"choices": [{"message": {"content": ""}}]})
    assert client.chat("sys", "usr") is None


def test_the_api_key_is_only_ever_a_header():
    """Regression guard: a persona prompt must not be able to reach the key."""
    cfg = LLMConfig(base_url="https://x/v1", model="m",
                    api_style="openai", api_key="sk-secret")
    client = _Fake(cfg, {"choices": [{"message": {"content": "hi"}}]})
    client.chat("sys", "usr")
    _, payload, _ = client.sent
    assert "sk-secret" not in json.dumps(payload)


def test_anthropic_style_is_inferred_from_the_host():
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.anthropic.com",
                           "HOBBIT_LLM_MODEL": "claude-sonnet-5",
                           "HOBBIT_LLM_KEY": "sk-ant-test"})
    assert cfg.api_style == "anthropic" and cfg.is_remote


def _anthropic_client(reply):
    return _Fake(LLMConfig(base_url="https://api.anthropic.com",
                           model="claude-sonnet-5", api_style="anthropic",
                           api_key="sk-ant-test"), reply)


def test_anthropic_chat_reads_a_content_block():
    client = _anthropic_client(
        {"content": [{"type": "text", "text": " Aye, and gladly. "}],
         "stop_reason": "end_turn"})
    assert client.chat("sys", "usr") == "Aye, and gladly."
    path, payload, _ = client.sent
    assert path == "/v1/messages"


def test_anthropic_system_prompt_is_top_level_not_a_message():
    """Sending it as a message role is the classic port bug -- the persona
    would be read as the player talking, not as the character's own nature."""
    client = _anthropic_client({"content": [{"type": "text", "text": "hi"}]})
    client.chat("You are Bofur.", "Greet Bilbo.")
    _, payload, _ = client.sent
    assert payload["system"] == "You are Bofur."
    assert [m["role"] for m in payload["messages"]] == ["user"]


def test_anthropic_thinking_is_disabled():
    """Left unset, adaptive thinking runs and eats the whole 90-token budget
    before any dialogue is written -- the companion would fall silent."""
    client = _anthropic_client({"content": [{"type": "text", "text": "hi"}]})
    client.chat("sys", "usr")
    _, payload, _ = client.sent
    assert payload["thinking"] == {"type": "disabled"}


def test_anthropic_sends_no_temperature():
    """A non-default temperature is a 400 on the current Sonnet."""
    client = _anthropic_client({"content": [{"type": "text", "text": "hi"}]})
    client.chat("sys", "usr")
    _, payload, _ = client.sent
    assert "temperature" not in payload


def test_anthropic_refusal_falls_back_rather_than_speaking_nothing():
    client = _anthropic_client({"content": [], "stop_reason": "refusal"})
    assert client.chat("sys", "usr") is None


def test_anthropic_auth_uses_the_right_headers():
    cfg = LLMConfig(base_url="https://api.anthropic.com", model="m",
                    api_style="anthropic", api_key="sk-ant-secret")
    captured = {}

    class _H(LLMClient):
        def _post(self, path, payload, timeout):
            # re-run the header assembly the real _post does
            import hobbit.llm as m
            h = {"Content-Type": "application/json"}
            if self.config.api_style == m.ANTHROPIC:
                h["x-api-key"] = self.config.api_key
                h["anthropic-version"] = m.ANTHROPIC_VERSION
            captured.update(h)
            captured["_body"] = json.dumps(payload)
            return {"content": [{"type": "text", "text": "hi"}]}

    _H(cfg).chat("sys", "usr")
    assert captured["x-api-key"] == "sk-ant-secret"
    assert "Authorization" not in captured        # not a bearer token API
    assert captured["anthropic-version"]
    assert "sk-ant-secret" not in captured["_body"]   # header only, never body


def test_claude_models_drop_temperature_even_through_a_proxy():
    """ppq.ai and friends pass the field straight through to Anthropic, which
    rejects a non-default temperature with a 400 -- so every companion line
    would fail in production."""
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.ppq.ai",
                           "HOBBIT_LLM_MODEL": "claude-sonnet-5",
                           "HOBBIT_LLM_KEY": "sk-test"})
    assert cfg.api_style == "openai"      # ppq speaks the OpenAI shape
    assert cfg.temperature is None

    client = _Fake(cfg, {"choices": [{"message": {"content": "Aye."}}]})
    client.chat("sys", "usr")
    _, payload, _ = client.sent
    assert "temperature" not in payload


def test_a_non_claude_model_keeps_its_temperature():
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.ppq.ai",
                           "HOBBIT_LLM_MODEL": "glm-5.2",
                           "HOBBIT_LLM_KEY": "sk-test"})
    assert cfg.temperature == 0.9
    client = _Fake(cfg, {"choices": [{"message": {"content": "Aye."}}]})
    client.chat("sys", "usr")
    _, payload, _ = client.sent
    assert payload["temperature"] == 0.9


def test_temperature_and_budget_can_be_overridden_from_the_environment():
    base = {"HOBBIT_LLM_URL": "https://api.ppq.ai", "HOBBIT_LLM_MODEL": "glm-5.2",
            "HOBBIT_LLM_KEY": "k"}
    assert config_from_env({**base, "HOBBIT_LLM_TEMPERATURE": "none"}).temperature is None
    assert config_from_env({**base, "HOBBIT_LLM_TEMPERATURE": "0.3"}).temperature == 0.3
    assert config_from_env({**base, "HOBBIT_LLM_MAX_TOKENS": "400"}).max_tokens == 400


def test_a_key_file_is_preferred_over_the_variable(tmp_path):
    """A file is how Docker and Kubernetes secrets arrive, and unlike a
    variable it isn't inherited by child processes or dumped by
    `docker inspect`."""
    f = tmp_path / "llm.key"
    f.write_text("sk-from-file\n", encoding="utf-8")   # editors add a newline
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.ppq.ai",
                           "HOBBIT_LLM_MODEL": "glm-5.2",
                           "HOBBIT_LLM_KEY": "sk-from-env",
                           "HOBBIT_LLM_KEY_FILE": str(f)})
    assert cfg.api_key == "sk-from-file"       # file wins
    assert "\n" not in cfg.api_key             # a trailing newline is a 401


def test_a_missing_key_file_degrades_rather_than_crashing(tmp_path):
    """A secret mount that didn't appear should cost the companions their
    voices, not take the server down at startup."""
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.ppq.ai",
                           "HOBBIT_LLM_MODEL": "glm-5.2",
                           "HOBBIT_LLM_KEY": "sk-fallback",
                           "HOBBIT_LLM_KEY_FILE": str(tmp_path / "absent")})
    assert cfg.api_key == "sk-fallback"


def test_the_variable_still_works_because_platforms_only_offer_that():
    """Fly and Cloud Run deliver stored secrets as environment variables."""
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.ppq.ai",
                           "HOBBIT_LLM_MODEL": "glm-5.2",
                           "HOBBIT_LLM_KEY": "  sk-padded  "})
    assert cfg.api_key == "sk-padded"


def _key_env(tmp_path, contents, **extra):
    f = tmp_path / "secrets.json"
    f.write_text(contents, encoding="utf-8")
    return {"HOBBIT_LLM_URL": "https://api.ppq.ai",
            "HOBBIT_LLM_MODEL": "claude-sonnet-5",
            "HOBBIT_LLM_KEY_FILE": str(f), **extra}


def test_a_json_secrets_file_yields_the_key_not_the_whole_blob(tmp_path):
    """A hand-rolled secrets file is JSON. Sending the blob as a bearer token
    gives a 401 that looks exactly like a wrong key."""
    for field in ("api_key", "apiKey", "key", "token", "PPQ_API_KEY"):
        env = _key_env(tmp_path, json.dumps({field: "sk-the-real-key"}))
        assert config_from_env(env).api_key == "sk-the-real-key", field


def test_the_field_can_be_named_when_the_guess_would_be_wrong(tmp_path):
    env = _key_env(tmp_path,
                   json.dumps({"api_key": "sk-openai-one",
                               "ppq": "sk-the-ppq-one"}),
                   HOBBIT_LLM_KEY_FIELD="ppq")
    assert config_from_env(env).api_key == "sk-the-ppq-one"


def test_a_lone_plausible_secret_is_found_under_any_field_name(tmp_path):
    env = _key_env(tmp_path, json.dumps({"wildly_unexpected_name":
                                         "sk-abcdefghijklmnopqrstuvwxyz"}))
    assert config_from_env(env).api_key == "sk-abcdefghijklmnopqrstuvwxyz"


def test_an_ambiguous_json_file_refuses_to_guess(tmp_path):
    """Two candidates and no named field: better to fall back than to send
    the wrong project's key to a provider."""
    env = _key_env(tmp_path, json.dumps({"one": "sk-aaaaaaaaaaaaaaaaaaaaaa",
                                         "two": "sk-bbbbbbbbbbbbbbbbbbbbbb"}),
                   HOBBIT_LLM_KEY="sk-from-env")
    assert config_from_env(env).api_key == "sk-from-env"


def test_a_bare_token_file_still_works(tmp_path):
    f = tmp_path / "llm.key"
    f.write_text("sk-bare-token\n", encoding="utf-8")
    cfg = config_from_env({"HOBBIT_LLM_URL": "https://api.ppq.ai",
                           "HOBBIT_LLM_MODEL": "glm-5.2",
                           "HOBBIT_LLM_KEY_FILE": str(f)})
    assert cfg.api_key == "sk-bare-token"


def test_no_fast_model_leaves_the_single_model_setup_alone():
    from hobbit.llm import fast_config_from_env
    assert fast_config_from_env({"HOBBIT_LLM_URL": "https://api.ppq.ai",
                                 "HOBBIT_LLM_MODEL": "claude-sonnet-5",
                                 "HOBBIT_LLM_KEY": "k"}) is None


def test_the_fast_client_shares_everything_but_the_model():
    from hobbit.llm import fast_config_from_env
    env = {"HOBBIT_LLM_URL": "https://api.ppq.ai",
           "HOBBIT_LLM_MODEL": "claude-sonnet-5",
           "HOBBIT_LLM_FAST_MODEL": "claude-haiku-4.5",
           "HOBBIT_LLM_KEY": "sk-test"}
    main, fast = config_from_env(env), fast_config_from_env(env)
    assert main.model == "claude-sonnet-5"
    assert fast.model == "claude-haiku-4.5"
    assert (fast.base_url, fast.api_key, fast.api_style) == \
           (main.base_url, main.api_key, main.api_style)
    assert fast.temperature is None      # still a Claude model


def test_goal_picks_use_the_fast_client_and_dialogue_does_not():
    """Three quarters of a run's calls are one-word goal picks. Sending those
    to the cheap model is where the saving is, without touching the lines a
    player reads."""
    from hobbit.game import Game

    class Spy:
        def __init__(self): self.calls = 0
        def chat(self, system, user):
            self.calls += 1
            return "ADVANCE" if "keyword" in system.lower() else "A line."

    # The mechanical majority goes to the cheap client.
    good, cheap = Spy(), Spy()
    game = Game(seed=3, llm=good, llm_fast=cheap)
    game.player.light_remaining = 99999
    for i in range(40):
        game.process_player_input("east" if i % 5 else "wait")
    assert cheap.calls > 0, "goal picks should have gone to the cheap model"

    # Dialogue still goes to the good one. Checked on a fresh game: forty
    # turns of marching leaves Bilbo fainting and Thorin dead in the trolls'
    # clearing, which says nothing about which client was used.
    good2, cheap2 = Spy(), Spy()
    fresh = Game(seed=3, llm=good2, llm_fast=cheap2)
    before = good2.calls
    fresh.process_player_input("talk to thorin")
    assert good2.calls > before, "dialogue must still use the good model"


def test_one_client_still_works_when_no_fast_model_is_configured():
    """The single-model setup has to be untouched by all this."""
    from hobbit.game import Game

    class Spy:
        def __init__(self): self.calls = 0
        def chat(self, system, user):
            self.calls += 1
            return "ADVANCE" if "keyword" in system.lower() else "A line."

    only = Spy()
    game = Game(seed=3, llm=only)          # no llm_fast
    game.player.light_remaining = 99999
    for i in range(20):
        game.process_player_input("wait")
    assert only.calls > 0
