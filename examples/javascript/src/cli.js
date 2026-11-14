#!/usr/bin/env node
// @ts-check
/**
 * Usage:
 *   node src/cli.js generate "<prompt>" [--image in.png ...] [--name cat] [--out-dir output] [--model id]
 *   node src/cli.js chat [--image in.png] [--name turn] [--out-dir output] [--model id]
 */
import { realpathSync } from "node:fs";
import { createInterface } from "node:readline/promises";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { ApiError } from "@google/genai";
import {
  NanoBananaError,
  buildContents,
  createClient,
  generate,
  getModelId,
  handleResponse,
} from "./nano-banana.js";

export const USAGE = `Usage:
  nano-banana generate "<prompt>" [-i image]... [-n name] [-o out-dir] [--model id]
  nano-banana chat [-i image]... [-n name] [-o out-dir] [--model id]

Environment:
  GEMINI_API_KEY       API key from https://aistudio.google.com/apikey (required)
  GEMINI_IMAGE_MODEL   Model ID override (default: gemini-2.5-flash-image)`;

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
      help: { type: "boolean", short: "h", default: false },
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
    help: values.help ?? false,
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
    error(`error: ${/** @type {Error} */ (err).message}\n\n${USAGE}`);
    return 1;
  }
  if (args.help || !args.command) {
    log(USAGE);
    return args.help ? 0 : 1;
  }
  const model = args.model ?? getModelId();

  try {
    const client = deps.client ?? createClient();
    if (args.command === "generate") {
      const result = await generate(client, args.prompt, {
        imagePaths: args.images,
        model,
        outDir: args.outDir,
        stem: args.name ?? "image",
      });
      report(result, log);
    } else if (args.command === "chat") {
      await runChat(client, model, args, log, deps.input ?? process.stdin);
    } else {
      error(`error: unknown command "${args.command}"\n\n${USAGE}`);
      return 1;
    }
  } catch (err) {
    if (err instanceof ApiError) {
      error(`error: Gemini API request failed (${err.status}): ${apiErrorMessage(err)}`);
      return 2;
    }
    if (err instanceof NanoBananaError || err instanceof TypeError || isFsError(err)) {
      error(`error: ${/** @type {Error} */ (err).message}`);
      return 1;
    }
    throw err;
  }
  return 0;
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
 * @param {(s: string) => void} log
 * @param {NodeJS.ReadableStream} input
 */
async function runChat(client, model, args, log, input) {
  const chat = client.chats.create({ model, config: { responseModalities: ["TEXT", "IMAGE"] } });
  const rl = createInterface({ input, terminal: false });
  let pendingImages = args.images;
  let turn = 0;
  try {
    log("Describe an image, then keep refining it. Empty line to quit.");
    for await (const line of rl) {
      const prompt = line.trim();
      if (!prompt) break;
      turn += 1;
      const message = await buildContents(prompt, pendingImages);
      pendingImages = []; // input images are only sent with the first message
      const response = await chat.sendMessage({ message });
      report(await handleResponse(response, args.outDir, `${args.name ?? "turn"}-${turn}`), log);
    }
  } finally {
    rl.close();
  }
}

const isEntryPoint =
  process.argv[1] !== undefined && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url);
if (isEntryPoint) {
  process.exitCode = await main(process.argv.slice(2));
}
