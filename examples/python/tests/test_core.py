from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.genai import types

from nano_banana import core

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"
JPEG_BYTES = b"\xff\xd8\xfffake"


def make_response(*parts: types.Part, **kwargs) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))],
        **kwargs,
    )


def image_part(data: bytes = PNG_BYTES, mime: str = "image/png") -> types.Part:
    return types.Part.from_bytes(data=data, mime_type=mime)


class TestConfig:
    def test_prefers_gemini_api_key(self):
        env = {"GEMINI_API_KEY": "gemini", "GOOGLE_API_KEY": "google"}
        assert core.get_api_key(env) == "gemini"

    def test_falls_back_to_google_api_key(self):
        assert core.get_api_key({"GEMINI_API_KEY": "  ", "GOOGLE_API_KEY": "google"}) == "google"

    def test_missing_key_raises_helpful_error(self):
        with pytest.raises(core.MissingApiKeyError, match="GEMINI_API_KEY"):
            core.get_api_key({})

    def test_model_defaults_and_override(self):
        assert core.get_model_id({}) == core.DEFAULT_MODEL
        assert core.get_model_id({"GEMINI_IMAGE_MODEL": " custom-model "}) == "custom-model"


class TestMimeTypes:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("cat.png", "image/png"),
            ("lunch.JPG", "image/jpeg"),
            ("photo.jpeg", "image/jpeg"),
            ("x.webp", "image/webp"),
        ],
    )
    def test_guess_mime_type(self, name, expected):
        assert core.guess_mime_type(name) == expected

    @pytest.mark.parametrize("name", ["notes.txt", "noextension", "anim.gif"])
    def test_rejects_unsupported(self, name):
        with pytest.raises(core.UnsupportedImageError):
            core.guess_mime_type(name)

    @pytest.mark.parametrize(
        ("mime", "ext"),
        [("image/png", ".png"), ("image/jpeg", ".jpg"), ("IMAGE/WEBP", ".webp"), (None, ".png")],
    )
    def test_extension_for_mime(self, mime, ext):
        assert core.extension_for_mime(mime) == ext


class TestBuildContents:
    def test_prompt_only(self):
        contents = core.build_contents("a cat")
        assert len(contents) == 1
        assert contents[0].text == "a cat"

    def test_with_images_uses_correct_mime(self, tmp_path: Path):
        png = tmp_path / "cat.png"
        jpg = tmp_path / "lunch.jpg"
        png.write_bytes(PNG_BYTES)
        jpg.write_bytes(JPEG_BYTES)

        contents = core.build_contents("combine", [png, jpg])

        assert [c.inline_data.mime_type for c in contents[1:]] == ["image/png", "image/jpeg"]
        assert contents[2].inline_data.data == JPEG_BYTES

    def test_empty_prompt_rejected(self):
        with pytest.raises(ValueError):
            core.build_contents("   ")

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            core.build_contents("edit", [tmp_path / "missing.png"])


class TestResponseHandling:
    def test_extract_text_skips_images_and_thoughts(self):
        parts = [
            types.Part(text="thinking...", thought=True),
            types.Part(text="Here is your cat."),
            image_part(),
        ]
        assert core.extract_text(parts) == "Here is your cat."

    def test_single_image_saved_without_index(self, tmp_path: Path):
        paths = core.save_images([image_part()], tmp_path / "out", "cat")
        assert paths == (tmp_path / "out" / "cat.png",)
        assert paths[0].read_bytes() == PNG_BYTES

    def test_multiple_images_are_all_saved(self, tmp_path: Path):
        parts = [image_part(), types.Part(text="caption"), image_part(JPEG_BYTES, "image/jpeg")]
        paths = core.save_images(parts, tmp_path, "story")
        assert [p.name for p in paths] == ["story-1.png", "story-2.jpg"]
        assert paths[1].read_bytes() == JPEG_BYTES

    def test_no_images_creates_nothing(self, tmp_path: Path):
        assert core.save_images([types.Part(text="no image")], tmp_path / "out") == ()
        assert not (tmp_path / "out").exists()

    def test_blocked_prompt_raises(self):
        response = types.GenerateContentResponse(
            prompt_feedback=types.GenerateContentResponsePromptFeedback(
                block_reason=types.BlockedReason.SAFETY
            )
        )
        with pytest.raises(core.EmptyResponseError, match="blocked"):
            core.response_parts(response)

    def test_empty_candidate_reports_finish_reason(self):
        response = types.GenerateContentResponse(
            candidates=[types.Candidate(finish_reason=types.FinishReason.IMAGE_SAFETY)]
        )
        with pytest.raises(core.EmptyResponseError, match="IMAGE_SAFETY"):
            core.response_parts(response)

    def test_handle_response(self, tmp_path: Path):
        result = core.handle_response(
            make_response(types.Part(text="Done"), image_part()), tmp_path, "x"
        )
        assert result.text == "Done"
        assert result.image_paths == (tmp_path / "x.png",)


def test_generate_calls_api_with_model_and_modalities(tmp_path: Path):
    client = MagicMock()
    client.models.generate_content.return_value = make_response(image_part())

    result = core.generate(client, "a banana", model="m-1", out_dir=tmp_path, stem="banana")

    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "m-1"
    assert kwargs["contents"][0].text == "a banana"
    assert kwargs["config"].response_modalities == ["TEXT", "IMAGE"]
    assert result.image_paths == (tmp_path / "banana.png",)
