import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import {
  ImageNotFoundError,
  checkImagePaths,
  DEFAULT_MODEL,
  EmptyResponseError,
  MissingApiKeyError,
  UnsupportedImageError,
  buildContents,
  extensionForMime,
  extractText,
  generate,
  getApiKey,
  getModelId,
  guessMimeType,
  responseParts,
  saveImages,
} from "../src/nano-banana.js";

const b64 = (s) => Buffer.from(s).toString("base64");
const imagePart = (data = "png-bytes", mimeType = "image/png") => ({
  inlineData: { data: b64(data), mimeType },
});
const response = (...parts) => ({ candidates: [{ content: { parts } }] });
const tempDir = () => mkdtemp(path.join(tmpdir(), "nano-banana-"));

describe("config", () => {
  it("prefers GEMINI_API_KEY and falls back to GOOGLE_API_KEY", () => {
    assert.equal(getApiKey({ GEMINI_API_KEY: "a", GOOGLE_API_KEY: "b" }), "a");
    assert.equal(getApiKey({ GEMINI_API_KEY: " ", GOOGLE_API_KEY: "b" }), "b");
  });

  it("throws a helpful error when no key is set", () => {
    assert.throws(() => getApiKey({}), MissingApiKeyError);
    assert.throws(() => getApiKey({}), /GEMINI_API_KEY/);
  });

  it("resolves the model from the environment", () => {
    assert.equal(getModelId({}), DEFAULT_MODEL);
    assert.equal(getModelId({ GEMINI_IMAGE_MODEL: " other " }), "other");
  });
});

describe("mime types", () => {
  it("maps file extensions", () => {
    assert.equal(guessMimeType("cat.png"), "image/png");
    assert.equal(guessMimeType("lunch.JPG"), "image/jpeg");
    assert.equal(guessMimeType("x.webp"), "image/webp");
  });

  it("rejects unsupported files", () => {
    assert.throws(() => guessMimeType("notes.txt"), UnsupportedImageError);
    assert.throws(() => guessMimeType("noext"), UnsupportedImageError);
  });

  it("maps output mime types to extensions", () => {
    assert.equal(extensionForMime("image/jpeg"), ".jpg");
    assert.equal(extensionForMime("IMAGE/PNG"), ".png");
    assert.equal(extensionForMime(undefined), ".png");
  });
});

describe("buildContents", () => {
  it("puts the prompt first and encodes images with the right mime type", async () => {
    const dir = await tempDir();
    const jpg = path.join(dir, "lunch.jpg");
    await writeFile(jpg, "jpeg-bytes");

    const contents = await buildContents("restore this", [jpg]);

    assert.deepEqual(contents[0], { text: "restore this" });
    assert.deepEqual(contents[1], {
      inlineData: { mimeType: "image/jpeg", data: b64("jpeg-bytes") },
    });
  });

  it("rejects an empty prompt", async () => {
    await assert.rejects(buildContents("  "), TypeError);
  });
});

describe("response handling", () => {
  it("extracts text without thoughts", () => {
    const parts = [{ text: "hmm", thought: true }, { text: "Here you go" }, imagePart()];
    assert.equal(extractText(parts), "Here you go");
  });

  it("saves a single image without an index", async () => {
    const dir = await tempDir();
    const files = await saveImages([imagePart("abc")], dir, "cat");
    assert.deepEqual(files, [path.join(dir, "cat.png")]);
    assert.equal(await readFile(files[0], "utf8"), "abc");
  });

  it("saves every image when there are several", async () => {
    const dir = await tempDir();
    const parts = [imagePart("1"), { text: "caption" }, imagePart("2", "image/jpeg")];
    await saveImages(parts, dir, "story");
    assert.deepEqual((await readdir(dir)).sort(), ["story-1.png", "story-2.jpg"]);
  });

  it("returns no files when there are no images", async () => {
    assert.deepEqual(await saveImages([{ text: "hi" }], "unused-dir"), []);
  });

  it("explains blocked or empty responses", () => {
    assert.throws(
      () => responseParts({ promptFeedback: { blockReason: "SAFETY" } }),
      (err) => err instanceof EmptyResponseError && /blocked \(SAFETY\)/.test(err.message),
    );
    assert.throws(
      () => responseParts({ candidates: [{ finishReason: "IMAGE_SAFETY" }] }),
      /IMAGE_SAFETY/,
    );
  });
});

describe("generate", () => {
  it("calls the API with the model and image modality, then saves output", async () => {
    const dir = await tempDir();
    let request;
    const client = {
      models: {
        generateContent: async (req) => {
          request = req;
          return response({ text: "A banana" }, imagePart("img"));
        },
      },
    };

    const result = await generate(client, "a banana", { model: "m-1", outDir: dir, stem: "b" });

    assert.equal(request.model, "m-1");
    assert.deepEqual(request.config.responseModalities, ["TEXT", "IMAGE"]);
    assert.deepEqual(request.contents, [{ text: "a banana" }]);
    assert.equal(result.text, "A banana");
    assert.deepEqual(result.imagePaths, [path.join(dir, "b.png")]);
  });
});

describe("checkImagePaths", () => {
  it("accepts existing images and rejects missing or unsupported files", async () => {
    const dir = await mkdtemp(path.join(tmpdir(), "nb-check-"));
    const good = path.join(dir, "a.png");
    await writeFile(good, "x");
    await checkImagePaths([good]);
    await assert.rejects(checkImagePaths([path.join(dir, "missing.jpg")]), ImageNotFoundError);
    await assert.rejects(checkImagePaths([dir]), UnsupportedImageError);
    await assert.rejects(checkImagePaths([path.join(dir, "folder.png")]), ImageNotFoundError);
  });
});
