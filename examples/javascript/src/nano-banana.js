// @ts-check
/**
 * Small helpers around Gemini's image model ("Nano Banana") using @google/genai.
 * Everything except createClient/generate is pure, so it can be unit-tested
 * without an API key.
 */
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { GoogleGenAI } from "@google/genai";

export const API_KEY_ENV_VARS = ["GEMINI_API_KEY", "GOOGLE_API_KEY"];
export const MODEL_ENV_VAR = "GEMINI_IMAGE_MODEL";
export const DEFAULT_MODEL = "gemini-2.5-flash-image";

/** @type {Record<string, string>} */
const MIME_BY_EXTENSION = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".heic": "image/heic",
  ".heif": "image/heif",
};

/** @type {Record<string, string>} */
const EXTENSION_BY_MIME = {
  "image/png": ".png",
  "image/jpeg": ".jpg",
  "image/webp": ".webp",
  "image/heic": ".heic",
  "image/heif": ".heif",
};

/** Base class for errors raised by these helpers. */
export class NanoBananaError extends Error {
  /** @param {string} message */
  constructor(message) {
    super(message);
    this.name = new.target.name;
  }
}
export class MissingApiKeyError extends NanoBananaError {}
export class UnsupportedImageError extends NanoBananaError {}
export class ImageNotFoundError extends NanoBananaError {}
export class EmptyResponseError extends NanoBananaError {}

/**
 * @typedef {{ text?: string, thought?: boolean, inlineData?: { data?: string, mimeType?: string } }} Part
 * @typedef {{
 *   candidates?: Array<{ content?: { parts?: Part[] }, finishReason?: string }>,
 *   promptFeedback?: { blockReason?: string },
 * }} ResponseLike
 */

/**
 * Return the first non-empty API key from GEMINI_API_KEY / GOOGLE_API_KEY.
 * @param {Record<string, string | undefined>} [env]
 */
export function getApiKey(env = process.env) {
  for (const name of API_KEY_ENV_VARS) {
    const value = env[name]?.trim();
    if (value) return value;
  }
  throw new MissingApiKeyError(
    "No API key found. Set GEMINI_API_KEY (see .env.example); " +
      "create a key at https://aistudio.google.com/apikey.",
  );
}

/**
 * Return the image model to use, overridable with GEMINI_IMAGE_MODEL.
 * @param {Record<string, string | undefined>} [env]
 */
export function getModelId(env = process.env) {
  return env[MODEL_ENV_VAR]?.trim() || DEFAULT_MODEL;
}

/** @param {string} [apiKey] */
export function createClient(apiKey) {
  return new GoogleGenAI({ apiKey: apiKey ?? getApiKey() });
}

/** @param {string} filePath */
export function guessMimeType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const mime = MIME_BY_EXTENSION[ext];
  if (!mime) {
    throw new UnsupportedImageError(
      `Unsupported image type "${ext || "(none)"}" for ${filePath}; ` +
        `expected one of ${Object.keys(MIME_BY_EXTENSION).sort().join(", ")}.`,
    );
  }
  return mime;
}

/**
 * Fail fast, before any API call, if an input image is missing or has an unsupported type.
 * @param {string[]} imagePaths
 */
export async function checkImagePaths(imagePaths) {
  for (const filePath of imagePaths) {
    guessMimeType(filePath);
    const info = await stat(filePath).catch(() => undefined);
    if (!info?.isFile()) throw new ImageNotFoundError(`Input image not found: ${filePath}`);
  }
}

/** @param {string | undefined} mimeType */
export function extensionForMime(mimeType) {
  const key = mimeType?.split(";")[0].trim().toLowerCase() ?? "";
  return EXTENSION_BY_MIME[key] ?? ".png";
}

/**
 * Read an image file into an inline-data part.
 * @param {string} filePath
 * @returns {Promise<Part>}
 */
export async function loadImagePart(filePath) {
  const mimeType = guessMimeType(filePath);
  const data = await readFile(filePath);
  return { inlineData: { mimeType, data: data.toString("base64") } };
}

/**
 * Build request contents: the text prompt followed by any input images.
 * @param {string} prompt
 * @param {string[]} [imagePaths]
 * @returns {Promise<Part[]>}
 */
export async function buildContents(prompt, imagePaths = []) {
  if (!prompt?.trim()) throw new TypeError("Prompt must not be empty.");
  const images = await Promise.all(imagePaths.map(loadImagePart));
  return [{ text: prompt }, ...images];
}

/**
 * Return the parts of the first candidate, or throw a helpful error if there are none.
 * @param {ResponseLike} response
 * @returns {Part[]}
 */
export function responseParts(response) {
  const parts = response.candidates?.[0]?.content?.parts;
  if (parts?.length) return parts;

  let reason = "";
  if (response.promptFeedback?.blockReason) {
    reason = `: prompt blocked (${response.promptFeedback.blockReason})`;
  } else if (response.candidates?.[0]?.finishReason) {
    reason = `: finish reason ${response.candidates[0].finishReason}`;
  }
  throw new EmptyResponseError(`The model returned no content${reason}.`);
}

/** @param {Part[]} parts */
export function extractText(parts) {
  return parts
    .filter((p) => p.text && !p.thought)
    .map((p) => p.text)
    .join("\n")
    .trim();
}

/**
 * Write every inline image to outDir. One image is saved as `<stem>.<ext>`;
 * several are numbered `<stem>-1.<ext>`, `<stem>-2.<ext>`, ...
 * @param {Part[]} parts
 * @param {string} outDir
 * @param {string} [stem]
 * @returns {Promise<string[]>} the written file paths
 */
export async function saveImages(parts, outDir, stem = "image") {
  const images = parts.map((p) => p.inlineData).filter((d) => d?.data);
  if (images.length === 0) return [];

  await mkdir(outDir, { recursive: true });
  return Promise.all(
    images.map(async (blob, i) => {
      const suffix = images.length === 1 ? "" : `-${i + 1}`;
      const file = path.join(outDir, `${stem}${suffix}${extensionForMime(blob?.mimeType)}`);
      await writeFile(file, Buffer.from(blob?.data ?? "", "base64"));
      return file;
    }),
  );
}

/**
 * Extract text and save images from a response.
 * @param {ResponseLike} response
 * @param {string} outDir
 * @param {string} [stem]
 */
export async function handleResponse(response, outDir, stem = "image") {
  const parts = responseParts(response);
  return { text: extractText(parts), imagePaths: await saveImages(parts, outDir, stem) };
}

/**
 * Generate (or, with input images, edit/compose) images from a prompt.
 * @param {Pick<GoogleGenAI, "models">} client
 * @param {string} prompt
 * @param {{ imagePaths?: string[], model?: string, outDir?: string, stem?: string }} [options]
 */
export async function generate(client, prompt, options = {}) {
  const { imagePaths = [], model = getModelId(), outDir = "output", stem = "image" } = options;
  const response = await client.models.generateContent({
    model,
    contents: await buildContents(prompt, imagePaths),
    config: { responseModalities: ["TEXT", "IMAGE"] },
  });
  return handleResponse(/** @type {ResponseLike} */ (response), outDir, stem);
}
