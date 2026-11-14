"""Command-line interface: ``nano-banana generate`` and ``nano-banana chat``.

Results (model text and saved file paths) go to stdout; progress and errors go to
stderr, so ``nano-banana generate ... > log.txt`` still shows what is happening.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn

from google.genai import errors, types

from . import __version__
from .core import (
    DEFAULT_MODEL,
    GenerationResult,
    NanoBananaError,
    build_contents,
    check_image_paths,
    create_client,
    generate,
    get_model_id,
    handle_response,
)

EXIT_OK = 0
EXIT_USAGE = 1  # bad arguments, missing key, unreadable input, blocked prompt
EXIT_API = 2  # the Gemini API rejected the request
EXIT_INTERRUPTED = 130

EPILOG = f"""\
examples:
  nano-banana generate "A nano banana floating in space, studio lighting" -n banana
  nano-banana generate "Restore and colorize this photo" -i old.jpg -n restored
  nano-banana generate "Put the cat on this sofa" -i cat.png -i sofa.jpg
  nano-banana chat -i output/banana.png

environment:
  GEMINI_API_KEY       API key from https://aistudio.google.com/apikey (required;
                       GOOGLE_API_KEY is used as a fallback). Read from .env too.
  GEMINI_IMAGE_MODEL   model ID override (default: {DEFAULT_MODEL})

exit codes: 0 success, 1 usage or input error, 2 Gemini API error, 130 interrupted
"""


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that exits with :data:`EXIT_USAGE` (1) instead of argparse's 2.

    Exit code 2 is reserved for API errors, so scripts can tell the two apart.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _load_dotenv() -> None:
    """Load the nearest ``.env`` file if python-dotenv is installed (optional)."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover - optional dependency
        return
    # Search from the working directory upwards, not from this module's location.
    load_dotenv(find_dotenv(usecwd=True))


def _status(message: str, quiet: bool) -> None:
    if not quiet:
        print(message, file=sys.stderr, flush=True)


def _report(result: GenerationResult, out: Callable[[str], None] = print) -> None:
    if result.text:
        out(result.text)
    for path in result.image_paths:
        out(f"Saved {path}")
    if not result.image_paths:
        out("(The model returned no image this time; try rephrasing the prompt.)")


def _common_options() -> argparse.ArgumentParser:
    """Options accepted both before and after the subcommand.

    ``default=SUPPRESS`` keeps a subcommand from overwriting a value given before it;
    the real defaults are set once on the top-level parser. Each parser needs its own
    instance, because ``set_defaults`` mutates the (otherwise shared) action objects.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--model",
        default=argparse.SUPPRESS,
        metavar="ID",
        help=f"model ID (default: $GEMINI_IMAGE_MODEL or {DEFAULT_MODEL})",
    )
    common.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="DIR",
        help="directory for generated images, created if needed (default: ./output)",
    )
    common.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="don't print progress messages to stderr",
    )
    return common


def _image_option(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "-i",
        "--image",
        dest="images",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help=f"{help_text} (repeatable; PNG, JPEG, WebP, HEIC or HEIF)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="nano-banana",
        description="Generate and edit images with Gemini's image model (Nano Banana).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[_common_options()],
    )
    parser.set_defaults(model=None, out_dir=Path("output"), quiet=False)
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", title="commands")

    gen = sub.add_parser(
        "generate",
        parents=[_common_options()],
        help="create an image from a prompt, or edit/combine input images",
        description=(
            "Text-to-image. Pass one or more --image files to edit, restore or combine them."
        ),
        epilog=(
            "examples:\n"
            '  nano-banana generate "A watercolor fox in the snow" -n fox\n'
            '  nano-banana generate "Make it night time" -i output/fox.png -n fox-night'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    gen.add_argument("prompt", help="what to create, or how to change the input image(s)")
    _image_option(gen, "input image to edit or combine")
    gen.add_argument(
        "-n",
        "--name",
        default="image",
        metavar="STEM",
        help="output file name without extension (default: image)",
    )

    chat = sub.add_parser(
        "chat",
        parents=[_common_options()],
        help="refine an image over several turns",
        description=(
            "Interactive multi-turn editing: type one instruction per line and each result is "
            "saved as <name>-<turn>.png. Enter an empty line or press Ctrl-D to quit."
        ),
    )
    _image_option(chat, "starting image, sent with the first message")
    chat.add_argument(
        "-n",
        "--name",
        default="turn",
        metavar="STEM",
        help="output file name prefix (default: turn)",
    )
    return parser


def _run_chat(args: argparse.Namespace, model: str) -> int:
    client = create_client()
    session = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    _status(
        f"Chatting with {model}. Type an instruction per line; empty line or Ctrl-D to quit.",
        args.quiet,
    )
    pending_images: list[Path] = list(args.images)
    turn = 0
    while True:
        try:
            prompt = input("you> ").strip()
        except EOFError:
            print()
            return EXIT_OK
        if not prompt:
            return EXIT_OK
        turn += 1
        _status("Working...", args.quiet)
        try:
            response = session.send_message(build_contents(prompt, pending_images))
            pending_images = []  # input images are only sent with the first message
            _report(handle_response(response, args.out_dir, f"{args.name}-{turn}"))
        except NanoBananaError as exc:
            # A blocked or empty turn shouldn't end the session; let the user rephrase.
            print(f"error: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    model = args.model or get_model_id()
    try:
        # Validate everything local before touching the network.
        if args.command == "generate" and not args.prompt.strip():
            raise ValueError("Prompt must not be empty.")
        check_image_paths(args.images)

        if args.command == "chat":
            return _run_chat(args, model)

        client = create_client()
        _status(f"Generating with {model}...", args.quiet)
        result = generate(
            client,
            args.prompt,
            args.images,
            model=model,
            out_dir=args.out_dir,
            stem=args.name,
        )
        _report(result)
    except (NanoBananaError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except errors.APIError as exc:
        print(f"error: Gemini API request failed ({exc.code}): {exc.message}", file=sys.stderr)
        if exc.code == 404:
            print(
                f"hint: the model {model!r} may have been retired; "
                "set GEMINI_IMAGE_MODEL or pass --model.",
                file=sys.stderr,
            )
        return EXIT_API
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return EXIT_INTERRUPTED
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
