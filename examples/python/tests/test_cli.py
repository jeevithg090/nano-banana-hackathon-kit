from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.genai import errors, types

from nano_banana import cli


def _response() -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(text="A cat."),
                        types.Part.from_bytes(data=b"img", mime_type="image/png"),
                    ],
                )
            )
        ]
    )


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)


def test_missing_api_key_exits_with_error(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    assert cli.main(["generate", "a cat"]) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def test_generate_saves_image(monkeypatch, tmp_path: Path, capsys):
    client = MagicMock()
    client.models.generate_content.return_value = _response()
    monkeypatch.setattr(cli, "create_client", lambda: client)
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "env-model")

    code = cli.main(["-o", str(tmp_path), "generate", "a cat", "-n", "cat"])

    assert code == 0
    assert (tmp_path / "cat.png").read_bytes() == b"img"
    assert client.models.generate_content.call_args.kwargs["model"] == "env-model"
    out = capsys.readouterr().out
    assert "A cat." in out
    assert "cat.png" in out


def test_model_flag_overrides_env(monkeypatch, tmp_path: Path):
    client = MagicMock()
    client.models.generate_content.return_value = _response()
    monkeypatch.setattr(cli, "create_client", lambda: client)
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "env-model")

    cli.main(["--model", "flag-model", "-o", str(tmp_path), "generate", "a cat"])

    assert client.models.generate_content.call_args.kwargs["model"] == "flag-model"


def test_api_error_is_reported(monkeypatch, capsys, tmp_path: Path):
    client = MagicMock()
    client.models.generate_content.side_effect = errors.ClientError(
        404, {"error": {"code": 404, "message": "model not found", "status": "NOT_FOUND"}}
    )
    monkeypatch.setattr(cli, "create_client", lambda: client)

    assert cli.main(["-o", str(tmp_path), "generate", "a cat"]) == 2
    assert "model not found" in capsys.readouterr().err


def test_unsupported_input_image(monkeypatch, capsys, tmp_path: Path):
    monkeypatch.setattr(cli, "create_client", MagicMock)
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")

    assert cli.main(["generate", "edit", "-i", str(bad)]) == 1
    assert "Unsupported image type" in capsys.readouterr().err


def test_chat_sends_images_only_on_first_turn(monkeypatch, tmp_path: Path):
    img = tmp_path / "cat.png"
    img.write_bytes(b"png")
    session = MagicMock()
    session.send_message.return_value = _response()
    client = MagicMock()
    client.chats.create.return_value = session
    monkeypatch.setattr(cli, "create_client", lambda: client)
    inputs = iter(["make it a bengal cat", "add a party hat", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    code = cli.main(["-o", str(tmp_path / "out"), "chat", "-i", str(img)])

    assert code == 0
    first, second = (c.args[0] for c in session.send_message.call_args_list)
    assert len(first) == 2  # prompt + image
    assert len(second) == 1  # prompt only
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["turn-1.png", "turn-2.png"]


def test_options_are_accepted_after_the_subcommand(monkeypatch, tmp_path: Path):
    client = MagicMock()
    client.models.generate_content.return_value = _response()
    monkeypatch.setattr(cli, "create_client", lambda: client)

    code = cli.main(["generate", "a cat", "--model", "m", "-o", str(tmp_path), "-q"])

    assert code == 0
    assert client.models.generate_content.call_args.kwargs["model"] == "m"
    assert (tmp_path / "image.png").exists()


def test_option_before_subcommand_is_kept(monkeypatch, tmp_path: Path):
    client = MagicMock()
    client.models.generate_content.return_value = _response()
    monkeypatch.setattr(cli, "create_client", lambda: client)

    cli.main(["-o", str(tmp_path), "generate", "a cat"])

    assert (tmp_path / "image.png").exists()


def test_progress_goes_to_stderr_and_quiet_silences_it(monkeypatch, tmp_path: Path, capsys):
    client = MagicMock()
    client.models.generate_content.return_value = _response()
    monkeypatch.setattr(cli, "create_client", lambda: client)

    cli.main(["-o", str(tmp_path), "generate", "a cat"])
    captured = capsys.readouterr()
    assert "Generating with" in captured.err
    assert "Generating with" not in captured.out

    cli.main(["-o", str(tmp_path), "--quiet", "generate", "a cat"])
    assert capsys.readouterr().err == ""


def test_missing_input_image_fails_before_any_api_call(monkeypatch, capsys, tmp_path: Path):
    create = MagicMock()
    monkeypatch.setattr(cli, "create_client", create)

    assert cli.main(["generate", "edit", "-i", str(tmp_path / "missing.png")]) == 1
    assert "Input image not found" in capsys.readouterr().err
    create.assert_not_called()


def test_blank_prompt_is_a_usage_error(monkeypatch, capsys):
    create = MagicMock()
    monkeypatch.setattr(cli, "create_client", create)

    assert cli.main(["generate", "   "]) == 1
    assert "Prompt must not be empty" in capsys.readouterr().err
    create.assert_not_called()


def test_no_command_prints_help_and_exits_1(capsys):
    assert cli.main([]) == 1
    assert "commands:" in capsys.readouterr().err


def test_bad_arguments_exit_1_not_2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["paint"])
    assert excinfo.value.code == 1
    assert "invalid choice" in capsys.readouterr().err


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.startswith("nano-banana ")


def test_404_adds_a_model_hint(monkeypatch, capsys, tmp_path: Path):
    client = MagicMock()
    client.models.generate_content.side_effect = errors.ClientError(
        404, {"error": {"code": 404, "message": "model not found", "status": "NOT_FOUND"}}
    )
    monkeypatch.setattr(cli, "create_client", lambda: client)

    assert cli.main(["-o", str(tmp_path), "generate", "a cat"]) == 2
    assert "GEMINI_IMAGE_MODEL" in capsys.readouterr().err


def test_chat_keeps_going_after_a_blocked_turn(monkeypatch, tmp_path: Path, capsys):
    blocked = types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason="SAFETY")
    )
    session = MagicMock()
    session.send_message.side_effect = [blocked, _response()]
    client = MagicMock()
    client.chats.create.return_value = session
    monkeypatch.setattr(cli, "create_client", lambda: client)
    inputs = iter(["something blocked", "something fine", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    code = cli.main(["-o", str(tmp_path), "chat"])

    assert code == 0
    assert "prompt blocked" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == ["turn-2.png"]
