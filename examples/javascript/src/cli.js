#!/usr/bin/env node
// @ts-check
/**
 * Command-line interface: `nano-banana generate` and `nano-banana chat`.
 *
 * Results (model text and saved file paths) go to stdout; progress and errors go to
 * stderr, so `nano-banana generate ... > log.txt` still shows what is happening.
 */
import { readFileSync, realpathSync } from "node:fs";
import { createInterface } from "node:readline/promises";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { ApiError } from "@google/genai";
import {
  DEFAULT_MODEL,
  NanoBananaError,
  buildContents,
  checkImagePaths,
  createClient,
  generate,
  getModelId,
  handleResponse,
} from "./nano-banana.js";

export const EXIT_OK = 0;
export const EXIT_USAGE = 1; // bad arguments, missing key, unreadable input, blocked prompt
export const EXIT_API = 2; // the Gemini API rejected the request

export const VERSION = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
).version;

const OPTIONS = `Options:
  -i, --image FILE   Input image; repeatable (PNG, JPEG, WebP, HEIC, HEIF)
  -n, --name STEM    Output file name without extension
                     (default: "image" for generate, "turn" for chat)
  -o, --out-dir DIR  Directory for generated images, created if needed (default: output)
      --model ID     Model ID (default: $GEMINI_IMAGE_MODEL or ${DEFAULT_MODEL})
  -q, --quiet        Don't print progress messages to stderr
  -h, --help         Show help (also: nano-banana <command> --help)
  -V, --version      Show the version`;

export const USAGE = `nano-banana ${VERSION}: generate and edit images with Gemini's image model.

Usage:
  nano-banana generate "<prompt>" [-i image]... [-n name] [-o out-dir] [--model id]
  nano-banana chat [-i image]... [-n name] [-o out-dir] [--model id]

Commands:
  generate   Create an image from a prompt, or edit/combine the --image files
  chat       Refine an image over several turns (one instruction per line)

${OPTIONS}

Examples:
  nano-banana generate "A nano banana floating in space, studio lighting" -n banana
  nano-banana generate "Restore and colorize this photo" -i old.jpg -n restored
  nano-banana generate "Put the cat on this sofa" -i cat.png -i sofa.jpg
  nano-banana chat -i output/banana.png

Environment:
  GEMINI_API_KEY       API key from https://aistudio.google.com/apikey (required;
                       GOOGLE_API_KEY is used as a fallback)
  GEMINI_IMAGE_MODEL   Model ID override (default: ${DEFAULT_MODEL})

Exit codes: 0 success, 1 usage or input error, 2 Gemini API error, 130 interrupted`;

/** @type {Record<string, string>} */
const COMMAND_USAGE = {
  generate: `Usage: nano-banana generate "<prompt>" [-i image]... [-n name] [-o out-dir] [--model id]

Text-to-image. Pass one or more --image files to edit, restore or combine them.

${OPTIONS}

Examples:
  nano-banana generate "A watercolor fox in the snow" -n fox
  nano-banana generate "Make it night time" -i output/fox.png -n fox-night`,
  chat: `Usage: nano-banana chat [-i image]... [-n name] [-o out-dir] [--model id]

Interactive multi-turn editing: type one instruction per line and each result is
saved as <name>-<turn>.png. Enter an empty line or press Ctrl-D to quit.
Starting --image files are sent with the first message only.

${OPTIONS}`,
};

/** @param {string[]} argv */
export function parseCliArgs(argv) {
  const { values, positionals } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      image: { type: "string", short: "i", multiple: true, default: [] },
      name: { type: "string", short: "n" },
      "out-dir": { type: "string", short: "o", default: "output" },
      model: { type: "string" },
      quiet: { type: "boolean", short: "q", default: false },
      help: { type: "boolean", short: "h", default: false },
      version: { type: "boolean", short: "V", default: false },
    },
  });
  const [command, ...rest] = positionals;
  return {
    command,
    prompt: rest.join(" "),
    images: values.image ?? [],
    name: values.name,
    outDir: values["out-dir"] ?? "output",
    model: values.model,
    quiet: values.quiet ?? false,
    help: values.help ?? false,
    version: values.version ?? false,
  };
}

/** @param {{ text: string, imagePaths: string[] }} result @param {(s: string) => void} log */
function report(result, log) {
  if (result.text) log(result.text);
  for (const file of result.imagePaths) log(`Saved ${file}`);
  if (result.imagePaths.length === 0) {
    log("(The model returned no image this time; try rephrasing the prompt.)");
  }
}

/**
 * @param {string[]} argv
 * @param {{ client?: ReturnType<typeof createClient>, log?: (s: string) => void,
 *           error?: (s: string) => void, input?: NodeJS.ReadableStream }} [deps]
 * @returns {Promise<number>} process exit code
 */
export async function main(argv, deps = {}) {
  const log = deps.log ?? console.log;
  const error = deps.error ?? console.error;
  let args;
  try {
    args = parseCliArgs(argv);
  } catch (err) {
    error(`error: ${/** @type {Error} */ (err).message}\n\nRun "nano-banana --help" for usage.`);
    return EXIT_USAGE;
  }
  if (args.version) {
    log(`nano-banana ${VERSION}`);
    return EXIT_OK;
  }
  if (args.help) {
    log((args.command && COMMAND_USAGE[args.command]) || USAGE);
    return EXIT_OK;
  }
  if (!args.command) {
    error(USAGE);
    return EXIT_USAGE;
  }
  if (!(args.command in COMMAND_USAGE)) {
    error(`error: unknown command "${args.command}" (expected "generate" or "chat")\n\n${USAGE}`);
    return EXIT_USAGE;
  }
  if (args.command === "generate" && !args.prompt.trim()) {
    error(`error: generate needs a prompt\n\n${COMMAND_USAGE.generate}`);
    return EXIT_USAGE;
  }
  const model = args.model ?? getModelId();
  /** @param {string} s */
  const status = (s) => {
    if (!args.quiet) error(s);
  };

  try {
    // Validate everything local before touching the network.
    await checkImagePaths(args.images);
    const client = deps.client ?? createClient();
    if (args.command === "generate") {
      status(`Generating with ${model}...`);
      const result = await generate(client, args.prompt, {
        imagePaths: args.images,
        model,
        outDir: args.outDir,
        stem: args.name ?? "image",
      });
      report(result, log);
    } else {
      await runChat(client, model, args, { log, error, status }, deps.input ?? process.stdin);
    }
  } catch (err) {
    if (err instanceof ApiError) {
      error(`error: Gemini API request failed (${err.status}): ${apiErrorMessage(err)}`);
      if (err.status === 404) {
        error(
          `hint: the model "${model}" may have been retired; set GEMINI_IMAGE_MODEL or pass --model.`,
        );
      }
      return EXIT_API;
    }
    if (err instanceof NanoBananaError || err instanceof TypeError || isFsError(err)) {
      error(`error: ${/** @type {Error} */ (err).message}`);
      return EXIT_USAGE;
    }
    throw err;
  }
  return EXIT_OK;
}

/**
 * The SDK puts the raw JSON error body in `message`; surface just the human-readable part.
 * @param {ApiError} err
 */
export function apiErrorMessage(err) {
  try {
    return JSON.parse(err.message)?.error?.message ?? err.message;
  } catch {
    return err.message;
  }
}

/** @param {unknown} err */
function isFsError(err) {
  return err instanceof Error && "code" in err && typeof err.code === "string";
}

/**
 * @param {ReturnType<typeof createClient>} client
 * @param {string} model
 * @param {ReturnType<typeof parseCliArgs>} args
 * @param {{ log: (s: string) => void, error: (s: string) => void, status: (s: string) => void }} io
 * @param {NodeJS.ReadableStream} input
 */
async function runChat(client, model, args, io, input) {
  const chat = client.chats.create({ model, config: { responseModalities: ["TEXT", "IMAGE"] } });
  const rl = createInterface({ input, terminal: false });
  let pendingImages = args.images;
  let turn = 0;
  try {
    io.status(`Chatting with ${model}. Type an instruction per line; empty line to quit.`);
    for await (const line of rl) {
      const prompt = line.trim();
      if (!prompt) break;
      turn += 1;
      io.status("Working...");
      try {
        const message = await buildContents(prompt, pendingImages);
        const response = await chat.sendMessage({ message });
        pendingImages = []; // input images are only sent with the first message
        report(
          await handleResponse(response, args.outDir, `${args.name ?? "turn"}-${turn}`),
          io.log,
        );
      } catch (err) {
        // A blocked or empty turn shouldn't end the session; let the user rephrase.
        if (!(err instanceof NanoBananaError)) throw err;
        io.error(`error: ${err.message}`);
      }
    }
  } finally {
    rl.close();
  }
}

const isEntryPoint =
  process.argv[1] !== undefined && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url);
if (isEntryPoint) {
  process.once("SIGINT", () => {
    process.stderr.write("\n");
    process.exit(130);
  });
  process.exitCode = await main(process.argv.slice(2));
}
