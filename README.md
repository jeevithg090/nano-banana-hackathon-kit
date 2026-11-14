<p align="center">
  <img src="./assets/header.png" alt="Nano Banana 48 Hour Challenge banner" width="600"/>
</p>

# Nano Banana Hackathon Kit

A starter kit for building with **Gemini 2.5 Flash Image** ("Nano Banana"), Google's
image generation and editing model. It began as the official resource hub for the
[Nano Banana 48 Hour Challenge](https://www.kaggle.com/competitions/banana) hosted by
Google DeepMind on Kaggle in September 2025. This fork keeps those guides and adds tested,
runnable Python and JavaScript examples that you can build on.

> **Note:** The challenge ended on September 7, 2025, and its free 48-hour API tier is no
> longer available. The guides and examples still work with a regular Gemini API key. The
> original competition details are kept [below](#-the-original-challenge) for reference.

## Contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Architecture](#architecture)
- [Development](#development)
- [Using it in your own project](#using-it-in-your-own-project)
- [Project structure](#project-structure)
- [Resources](#resources)
- [The original challenge](#-the-original-challenge)
- [Credits and license](#credits-and-license)

## Features

- **Two step-by-step notebooks** (they run in Colab or locally):
  - [Getting your API key](./guides/01-getting-your-api-key.ipynb): create a key and generate your first image.
  - [Using Nano Banana](./guides/02-use-nano-banana.ipynb): text-to-image, editing, multi-image stories, chat-based iteration and combining several pictures.
- **A JavaScript/TypeScript guide** ([`examples/javascript-getting-started.md`](./examples/javascript-getting-started.md)) with snippets for generation, editing, photo restoration, multi-image input and conversational editing.
- **Command-line tools in Python and JavaScript** that cover the same tasks:
  - `generate` does text-to-image, or edits, restores or combines images when you pass `--image` (once or several times).
  - `chat` refines an image over several turns.
  - Every returned image is saved. If a response holds several, they are numbered so none is overwritten.
  - Input MIME types are detected from the file extension (PNG, JPEG, WebP, HEIC/HEIF).
  - Errors are clear: a missing key, an unsupported file, a blocked prompt (with its reason) or an API failure each get their own message and exit code.
- **Configuration through environment variables only.** API keys never appear in code or notebooks.
- **Tests, linting and formatting** for both languages (pytest + Ruff, `node:test` + ESLint + Prettier).

## Tech stack

| Area       | Tools                                                                                                                              |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Model      | Gemini 2.5 Flash Image (`gemini-2.5-flash-image`) through the [Gemini API](https://ai.google.dev/gemini-api/docs/image-generation) |
| Python     | Python 3.10+, [`google-genai`](https://pypi.org/project/google-genai/), `python-dotenv`, pytest, Ruff                              |
| JavaScript | Node.js 22.9+, [`@google/genai`](https://www.npmjs.com/package/@google/genai), `node:test`, ESLint, Prettier                       |
| Notebooks  | Jupyter / Google Colab, Pillow, IPython                                                                                            |

## Quick start

### 1. Get an API key

Create a key in [Google AI Studio](https://aistudio.google.com/apikey). The
[first guide](./guides/01-getting-your-api-key.ipynb) walks you through it.

```bash
cp .env.example .env
# then edit .env and set GEMINI_API_KEY=...
```

### 2a. Run the notebooks

Open them in Colab with the badge at the top of each notebook, and add your key as a Colab
Secret named `GOOGLE_API_KEY`. To run them locally, set the `GEMINI_API_KEY` environment
variable first and use Jupyter.

### 2b. Python CLI

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # or: pip install -e ".[dev]" for tests and linting
nano-banana generate "A photorealistic orange cat with green eyes on a couch" --name cat
```

### 2c. JavaScript CLI

```bash
cd examples/javascript
npm install
npm start -- generate "A photorealistic orange cat with green eyes on a couch" --name cat
```

Generated images go to `./output/` by default.

## Configuration

Both CLIs pick up a `.env` file: the Python CLI looks in the current directory and its parents
(via `python-dotenv`), and `npm start` loads the repo-root `.env` with Node's
`--env-file-if-exists`. Variables already exported in your shell also work and take precedence.

| Variable             | Required | Default                  | Description                                                                         |
| -------------------- | -------- | ------------------------ | ----------------------------------------------------------------------------------- |
| `GEMINI_API_KEY`     | Yes      | none                     | Gemini API key from AI Studio. `GOOGLE_API_KEY` is used as a fallback if it is set. |
| `GEMINI_IMAGE_MODEL` | No       | `gemini-2.5-flash-image` | Image model ID. Change it to try a newer image model without editing code.          |

> The `gemini-2.5-flash-image-preview` model ID used during the hackathon has been retired;
> the examples now default to the generally available `gemini-2.5-flash-image`. Google
> retires model versions over time, so check the
> [Gemini API deprecations page](https://ai.google.dev/gemini-api/docs/deprecations) and
> update `GEMINI_IMAGE_MODEL` if needed.

## Usage

The Python (`nano-banana`) and JavaScript (`npm start --`) CLIs take the same arguments.

```bash
# Text to image
nano-banana generate "A nano banana floating in space, studio lighting" --name banana

# Edit an image
nano-banana generate "Show this cat walking down a New York sidewalk" -i output/cat.png -n cat-nyc

# Restore an old photo (JPEG input is sent with the correct MIME type)
nano-banana generate "Restore and colorize this image from 1932" -i lunch.jpg -n restored

# Combine several images
nano-banana generate "Make the girl wear this t-shirt. Keep the background." -i girl.png -i tshirt.png

# Multi-turn refinement: type a prompt per line, empty line to quit
nano-banana chat -i output/cat.png
#   you> Change the cat to a bengal cat, leave everything else the same
#   you> Give it a funny party hat

# Global options go before the subcommand (Python) or anywhere (JavaScript)
nano-banana --model gemini-2.5-flash-image -o renders generate "..."
```

Exit codes: `0` success, `1` usage or input error (missing key, unsupported file, blocked
prompt), `2` Gemini API error.

## Architecture

Both implementations have the same two layers:

```
CLI (argument parsing, I/O, exit codes)
  └── cli.py / cli.js
        │
        ▼
Core helpers (no network except the client call)
  └── core.py / nano-banana.js
        get_api_key / getApiKey      ← env vars
        build_contents               ← prompt + images → inline-data parts (MIME by extension)
        generate                     → client.models.generate_content(..., modalities TEXT+IMAGE)
        response_parts               ← raises EmptyResponseError with block/finish reason
        extract_text / save_images   → text + numbered image files
```

The core functions are pure apart from the API call. Tests pass in real SDK response
objects (Python) or plain response objects (JavaScript) and a fake client, so they run
offline with no API key.

## Development

```bash
# Python (from the repo root)
pip install -e ".[dev]"
pytest                      # unit tests
ruff check .                # lint: Python package and notebooks
ruff format --check .       # formatting

# JavaScript
cd examples/javascript
npm install
npm test                    # node:test
npm run lint                # ESLint + Prettier check
npm run format              # apply Prettier
```

The tests mock the Gemini client and need no network access or API key. Generating real
images needs a valid `GEMINI_API_KEY`.

## Using it in your own project

This kit has no hosted service to deploy. It is a set of guides plus small libraries and CLIs.
To use the helpers in an app:

- **Python:** `pip install git+https://github.com/jeevithg090/nano-banana-hackathon-kit`,
  then `from nano_banana import create_client, generate`.
- **JavaScript:** copy `examples/javascript/src/nano-banana.js` into your project; its only
  dependency is `@google/genai`.
- **Keep the API key on the server.** Call Gemini from a backend or serverless function and
  set `GEMINI_API_KEY` in your hosting provider's secret settings. Never ship the key in
  browser code.

## Project structure

```
.
├── assets/header.png                    # README banner
├── guides/
│   ├── 01-getting-your-api-key.ipynb    # API key + first image
│   └── 02-use-nano-banana.ipynb         # generation, editing, stories, chat, compositing
├── examples/
│   ├── javascript-getting-started.md    # JS/TS snippets
│   ├── python/
│   │   ├── nano_banana/                 # core.py (helpers), cli.py, __main__.py
│   │   └── tests/                       # pytest suite
│   └── javascript/
│       ├── src/                         # nano-banana.js (helpers), cli.js
│       ├── test/                        # node:test suite
│       ├── eslint.config.js
│       └── package.json
├── .env.example                         # environment variable template
├── pyproject.toml                       # Python package, pytest and Ruff config
└── LICENSE                              # Apache 2.0
```

## Resources

- 🌐 [Gemini API image generation docs](https://ai.google.dev/gemini-api/docs/image-generation)
- ✍️ [Prompting guide and strategies](https://ai.google.dev/gemini-api/docs/image-generation#prompt-guide)
- 🍳 Cookbooks: [Python quickstart (Colab)](https://colab.research.google.com/github/google-gemini/cookbook/blob/main/quickstarts/Image_out.ipynb) ·
  [JavaScript starter (AI Studio)](https://aistudio.google.com/apps/bundled/get_started_image_out)
- ✨ Example AI Studio apps: [GemBooth](https://aistudio.google.com/apps/bundled/gembooth) ·
  [Home Canvas](https://aistudio.google.com/apps/bundled/home_canvas) ·
  [Past Forward](https://aistudio.google.com/apps/bundled/past_forward) ·
  [PixShop](https://aistudio.google.com/apps/bundled/pixshop)

**Partner resources from the challenge**

- ElevenLabs: [API quickstart](https://elevenlabs.io/docs/quickstart) ·
  [Agents platform](https://elevenlabs.io/docs/agents-platform/overview) ·
  [Showcase](https://showcase.elevenlabs.io/)
- fal.ai: [Create an account](https://fal.ai/) ·
  [API keys](https://fal.ai/dashboard/keys) ·
  [Quickstart](https://docs.fal.ai/model-apis/quickstart)

## 🍌 The original challenge

<details>
<summary>Competition details as published for the Nano Banana 48 Hour Challenge (September 2025)</summary>

For 48 hours starting September 6, 2025, Google DeepMind offered a special free tier of the
Gemini API for Gemini 2.5 Flash Image Preview. Together with fal and ElevenLabs, it put up
more than $400,000 in prizes. Participants were asked to build an application that changes how
people interact with visuals, for example:

- dynamic storytelling (such as comics with consistent characters),
- e-commerce (such as virtual room placement or product visualization),
- creative workflow automation (such as personalized marketing assets at scale),
- natural-language photo editors.

**Submission requirements** (on [Kaggle](https://www.kaggle.com/competitions/banana)):

1. A public video demo of 2 minutes or less.
2. A public project link: a live demo, or a code repository with setup instructions.
3. A write-up of up to 200 words on how Gemini 2.5 Flash Image was used.

**Judging criteria:** Innovation and "wow" factor (40%), technical execution (30%), potential
impact and utility (20%), presentation quality (10%). The ElevenLabs Special Technology Prize
used the same criteria, with a focus on ElevenLabs' contribution.

**Prizes:** Each of the top 50 submissions won $5,000 in Gemini API credits, $1,000 in fal credits
and 11M ElevenLabs credits. The ElevenLabs special prize was 22M ElevenLabs credits.

**Timeline:** The challenge started September 6, 2025 at 12:01 AM UTC. The submission deadline
was September 7, 2025. Judging ran September 8–17, and winners were announced on or around
September 19, 2025.

**API usage during the event:** The special free tier allowed 200 requests per project per day.
Paid API keys were billed as usual.

Discussion took place on the [Kaggle forum](https://www.kaggle.com/competitions/banana/discussion).

</details>

## Credits and license

The original guides, notebooks and banner are by Google LLC / Google DeepMind and the
contributors to
[google-gemini/nano-banana-hackathon-kit](https://github.com/google-gemini/nano-banana-hackathon-kit).
The project is licensed under the [Apache License 2.0](./LICENSE).
