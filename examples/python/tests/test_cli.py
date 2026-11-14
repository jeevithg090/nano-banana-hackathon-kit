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
