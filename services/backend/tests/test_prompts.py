import pytest

from app.ai.prompts import PromptManager

PINNED_CHAT_SYSTEM_V1_SHA256 = "5bd51c235339b517844f9a61a06763bb8aca344982c494567ba53a99cbe4bc37"


def test_chat_system_prompt_states_the_security_rules():
    text = PromptManager().get("chat_system").text

    assert "cannot run commands" in text
    assert "explicit approval" in text
    assert "Never reveal, repeat, or guess passwords, tokens, API keys" in text
    assert "highest priority" in text
    assert "<conversation>" in text
    assert "Never claim or imply that you performed an action" in text


def test_prompt_text_is_pinned_so_edits_are_deliberate():
    prompt = PromptManager().get("chat_system", "v1")

    assert prompt.sha256 == PINNED_CHAT_SYSTEM_V1_SHA256


def test_versions_are_discovered_in_numeric_order():
    assert PromptManager().versions("chat_system") == ["v1"]


def test_active_version_controls_the_default():
    manager = PromptManager("v1")

    assert manager.get("chat_system").version == "v1"


@pytest.mark.parametrize("name", ["../secrets", "chat_system/../x", "Chat", "", "a b"])
def test_prompt_names_cannot_traverse_the_filesystem(name):
    with pytest.raises(ValueError):
        PromptManager().get(name)


@pytest.mark.parametrize("version", ["v", "1", "v1/../../x", "latest", "v9"])
def test_bad_or_missing_versions_are_rejected(version):
    with pytest.raises(ValueError):
        PromptManager().get("chat_system", version)


def test_bad_active_version_is_rejected_at_startup():
    with pytest.raises(ValueError):
        PromptManager("../x")


def test_preferences_are_added_in_a_delimited_lower_priority_block():
    system = PromptManager().chat_system("Be brief")

    assert system.startswith(PromptManager().get("chat_system").text)
    assert "<user_preferences>\nBe brief\n</user_preferences>" in system
    assert "lower priority than the rules above" in system


def test_no_preferences_means_no_preferences_block():
    assert "user_preferences" not in PromptManager().chat_system(None)
    assert "user_preferences" not in PromptManager().chat_system("")


def test_render_fails_loudly_when_a_variable_is_missing():
    with pytest.raises(KeyError):
        PromptManager().render("preferences")
