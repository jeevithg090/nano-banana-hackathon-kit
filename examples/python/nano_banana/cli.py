"""Command-line interface: ``nano-banana generate`` and ``nano-banana chat``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from google.genai import errors, types

from .core import (
    GenerationResult,
    NanoBananaError,
    build_contents,
    create_client,
    generate,
    get_model_id,
    handle_response,
)


def _load_dotenv() -> None:
    """Load the nearest ``.env`` file if python-dotenv is installed (optional)."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover - optional dependency
        return
    # Search from the working directory upwards, not from this module's location.
    load_dotenv(find_dotenv(usecwd=True))


def _report(result: GenerationResult, out: Callable[[str], None] = print) -> None:
    if result.text:
        out(result.text)
    for path in result.image_paths:
        out(f"Saved {path}")
    if not result.image_paths:
        out("(The model returned no image this time; try rephrasing the prompt.)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nano-banana",
        description="Generate and edit images with Gemini's image model (Nano Banana).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID (default: $GEMINI_IMAGE_MODEL or gemini-2.5-flash-image).",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=Path("output"),
        help="Directory for generated images (default: ./output).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser(
        "generate",
        help="Generate an image from a prompt, optionally using input images.",
        description=(
            "Text-to-image, or pass one or more --image files to edit, restore or combine them."
        ),
    )
    gen.add_argument("prompt", help="What to create or how to change the input image(s).")
    gen.add_argument(
        "-i",
        "--image",
        dest="images",
        action="append",
        default=[],
        type=Path,
        help="Input image (repeatable).",
    )
    gen.add_argument("-n", "--name", default="image", help="Output file name stem.")

    chat = sub.add_parser(
        "chat",
        help="Iteratively refine an image over several turns.",
        description="Interactive multi-turn editing. Enter an empty line or Ctrl-D to quit.",
    )
    chat.add_argument("-i", "--image", dest="images", action="append", default=[], type=Path)
    chat.add_argument("-n", "--name", default="turn", help="Output file name stem.")
    return parser


def _run_chat(args: argparse.Namespace, model: str) -> None:
    client = create_client()
    session = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    pending_images: list[Path] = list(args.images)
    turn = 0
    while True:
        try:
            prompt = input("you> ").strip()
        except EOFError:
            print()
            return
        if not prompt:
            return
        turn += 1
        message = build_contents(prompt, pending_images)
        pending_images = []  # input images are only sent with the first message
        response = session.send_message(message)
        _report(handle_response(response, args.out_dir, f"{args.name}-{turn}"))


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv()
    args = build_parser().parse_args(argv)
    model = args.model or get_model_id()
    try:
        if args.command == "generate":
            result = generate(
                create_client(),
                args.prompt,
                args.images,
                model=model,
                out_dir=args.out_dir,
                stem=args.name,
            )
            _report(result)
        else:
            _run_chat(args, model)
    except (NanoBananaError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except errors.APIError as exc:
        print(f"error: Gemini API request failed ({exc.code}): {exc.message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
