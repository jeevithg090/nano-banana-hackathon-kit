"""Small, dependency-light helpers around the Gemini image model ("Nano Banana").

Everything here is pure (no network) apart from :func:`create_client`, so it can
be unit-tested without an API key.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from google import genai
from google.genai import types

API_KEY_ENV_VARS: tuple[str, ...] = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
MODEL_ENV_VAR = "GEMINI_IMAGE_MODEL"
DEFAULT_MODEL = "gemini-2.5-flash-image"

# Input formats accepted by the Gemini API for inline image data.
_MIME_BY_EXTENSION: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}
_EXTENSION_BY_MIME: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


class NanoBananaError(Exception):
    """Base class for errors raised by this package."""


class MissingApiKeyError(NanoBananaError):
    """Raised when no API key is configured."""


class UnsupportedImageError(NanoBananaError):
    """Raised when an input file is not an image format the API accepts."""


class ImageNotFoundError(NanoBananaError):
    """Raised when an input image path does not point to a readable file."""


class EmptyResponseError(NanoBananaError):
    """Raised when the model returns no content (for example, a blocked prompt)."""


@dataclass(frozen=True)
class GenerationResult:
    """Text and saved image paths extracted from a model response."""

    text: str
    image_paths: tuple[Path, ...]


def get_api_key(env: Mapping[str, str] | None = None) -> str:
    """Return the first non-empty API key found in ``GEMINI_API_KEY``/``GOOGLE_API_KEY``."""
    env = os.environ if env is None else env
    for name in API_KEY_ENV_VARS:
        value = env.get(name, "").strip()
        if value:
            return value
    raise MissingApiKeyError(
        "No API key found. Set GEMINI_API_KEY (see .env.example); "
        "create a key at https://aistudio.google.com/apikey."
    )


def get_model_id(env: Mapping[str, str] | None = None) -> str:
    """Return the image model to use, overridable with ``GEMINI_IMAGE_MODEL``."""
    env = os.environ if env is None else env
    return env.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL


def create_client(api_key: str | None = None) -> genai.Client:
    """Create a Gemini API client, reading the key from the environment if not given."""
    return genai.Client(api_key=api_key or get_api_key())


def guess_mime_type(path: str | os.PathLike[str]) -> str:
    """Map an image file path to the MIME type expected by the API."""
    suffix = Path(path).suffix.lower()
    try:
        return _MIME_BY_EXTENSION[suffix]
    except KeyError:
        supported = ", ".join(sorted(_MIME_BY_EXTENSION))
        raise UnsupportedImageError(
            f"Unsupported image type {suffix or '(none)'!r} for {path}; "
            f"expected one of {supported}."
        ) from None


def check_image_paths(paths: Iterable[str | os.PathLike[str]]) -> None:
    """Fail fast, before any API call, if an input image is missing or has an unsupported type."""
    for path in paths:
        guess_mime_type(path)
        if not Path(path).is_file():
            raise ImageNotFoundError(f"Input image not found: {path}")


def extension_for_mime(mime_type: str | None) -> str:
    """Return a file extension for an output MIME type (``.png`` if unknown)."""
    if not mime_type:
        return ".png"
    return _EXTENSION_BY_MIME.get(mime_type.split(";")[0].strip().lower(), ".png")


def load_image_part(path: str | os.PathLike[str]) -> types.Part:
    """Read an image file into an inline-data :class:`~google.genai.types.Part`."""
    mime_type = guess_mime_type(path)
    data = Path(path).read_bytes()
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def build_contents(
    prompt: str, image_paths: Sequence[str | os.PathLike[str]] = ()
) -> list[types.Part]:
    """Build request contents: the text prompt followed by any input images."""
    if not prompt.strip():
        raise ValueError("Prompt must not be empty.")
    return [types.Part.from_text(text=prompt), *(load_image_part(p) for p in image_paths)]


def response_parts(response: types.GenerateContentResponse) -> list[types.Part]:
    """Return the parts of the first candidate, raising a helpful error if there are none."""
    parts = response.parts
    if parts:
        return list(parts)

    reason = None
    if response.prompt_feedback and response.prompt_feedback.block_reason:
        reason = f"prompt blocked ({response.prompt_feedback.block_reason})"
    elif response.candidates and response.candidates[0].finish_reason:
        reason = f"finish reason {response.candidates[0].finish_reason}"
    raise EmptyResponseError("The model returned no content" + (f": {reason}." if reason else "."))


def extract_text(parts: Iterable[types.Part]) -> str:
    """Concatenate the text parts of a response (thought summaries excluded)."""
    return "\n".join(p.text for p in parts if p.text and not p.thought).strip()


def save_images(
    parts: Iterable[types.Part],
    out_dir: str | os.PathLike[str],
    stem: str = "image",
) -> tuple[Path, ...]:
    """Write every inline image in ``parts`` to ``out_dir`` and return the file paths.

    A single image is saved as ``<stem>.<ext>``; several are numbered
    ``<stem>-1.<ext>``, ``<stem>-2.<ext>``, ... so none is overwritten.
    """
    images = [p.inline_data for p in parts if p.inline_data and p.inline_data.data]
    if not images:
        return ()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, blob in enumerate(images, start=1):
        suffix = "" if len(images) == 1 else f"-{index}"
        path = out / f"{stem}{suffix}{extension_for_mime(blob.mime_type)}"
        path.write_bytes(blob.data)  # type: ignore[arg-type]  # checked non-empty above
        paths.append(path)
    return tuple(paths)


def handle_response(
    response: types.GenerateContentResponse,
    out_dir: str | os.PathLike[str],
    stem: str = "image",
) -> GenerationResult:
    """Extract text and save images from a response in one step."""
    parts = response_parts(response)
    return GenerationResult(text=extract_text(parts), image_paths=save_images(parts, out_dir, stem))


def generate(
    client: genai.Client,
    prompt: str,
    image_paths: Sequence[str | os.PathLike[str]] = (),
    *,
    model: str | None = None,
    out_dir: str | os.PathLike[str] = "output",
    stem: str = "image",
) -> GenerationResult:
    """Generate (or, with input images, edit/compose) images from a prompt."""
    response = client.models.generate_content(
        model=model or get_model_id(),
        contents=build_contents(prompt, image_paths),
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    return handle_response(response, out_dir, stem)
