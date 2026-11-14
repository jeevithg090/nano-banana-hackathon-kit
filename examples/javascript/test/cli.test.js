import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { Readable } from "node:stream";
import { describe, it } from "node:test";
import { ApiError } from "@google/genai";
import { VERSION, apiErrorMessage, main, parseCliArgs } from "../src/cli.js";

const image = {
  inlineData: { data: Buffer.from("img").toString("base64"), mimeType: "image/png" },
};
const okResponse = { candidates: [{ content: { parts: [{ text: "Done" }, image] } }] };

function capture() {
  const out = [];
  const err = [];
  return { out, err, log: (s) => out.push(s), error: (s) => err.push(s) };
}

describe("parseCliArgs", () => {
  it("parses a generate command with repeated images", () => {
    const args = parseCliArgs(["generate", "a", "cat", "-i", "x.png", "-i", "y.jpg", "-n", "c"]);
    assert.equal(args.command, "generate");
    assert.equal(args.prompt, "a cat");
    assert.deepEqual(args.images, ["x.png", "y.jpg"]);
    assert.equal(args.name, "c");
    assert.equal(args.outDir, "output");
  });
});

describe("main", () => {
  it("prints usage with --help", async () => {
    const io = capture();
    assert.equal(await main(["--help"], io), 0);
    assert.match(io.out.join("\n"), /GEMINI_API_KEY/);
  });

  it("reports a missing API key", async () => {
    const io = capture();
    const saved = { ...process.env };
    delete process.env.GEMINI_API_KEY;
    delete process.env.GOOGLE_API_KEY;
    try {
      assert.equal(await main(["generate", "a cat"], io), 1);
    } finally {
      Object.assign(process.env, saved);
    }
    assert.match(io.err.join("\n"), /No API key found/);
  });

  it("generates and saves an image", async () => {
    const dir = await mkdtemp(path.join(tmpdir(), "nb-cli-"));
    const io = capture();
    const client = { models: { generateContent: async () => okResponse } };

    const code = await main(["generate", "a cat", "-o", dir, "-n", "cat"], { ...io, client });

    assert.equal(code, 0);
    assert.deepEqual(await readdir(dir), ["cat.png"]);
    assert.match(io.out.join("\n"), /Saved .*cat\.png/);
  });

  it("maps API errors to exit code 2", async () => {
    const io = capture();
    const client = {
      models: {
        generateContent: async () => {
          throw new ApiError({ message: "model not found", status: 404 });
        },
      },
    };
    assert.equal(await main(["generate", "a cat"], { ...io, client }), 2);
    assert.match(io.err.join("\n"), /404/);
  });

  it("extracts the readable message from a JSON API error body", async () => {
    const body = JSON.stringify({ error: { code: 400, message: "API key not valid." } });
    assert.equal(
      apiErrorMessage(new ApiError({ message: body, status: 400 })),
      "API key not valid.",
    );
    assert.equal(apiErrorMessage(new ApiError({ message: "plain", status: 500 })), "plain");
  });

  it("rejects unknown commands", async () => {
    const io = capture();
    assert.equal(await main(["paint"], { ...io, client: {} }), 1);
    assert.match(io.err.join("\n"), /unknown command/);
  });

  it("chat sends input images only with the first message", async () => {
    const dir = await mkdtemp(path.join(tmpdir(), "nb-chat-"));
    const img = path.join(dir, "cat.png");
    await writeFile(img, "png");
    const sent = [];
    const client = {
      chats: {
        create: () => ({
          sendMessage: async ({ message }) => {
            sent.push(message);
            return okResponse;
          },
        }),
      },
    };
    const input = Readable.from(["make it bengal\n", "add a party hat\n", "\n"]);
    const out = path.join(dir, "out");

    const code = await main(["chat", "-i", img, "-o", out], { ...capture(), client, input });

    assert.equal(code, 0);
    assert.deepEqual(
      sent.map((m) => m.length),
      [2, 1],
    );
    assert.deepEqual((await readdir(out)).sort(), ["turn-1.png", "turn-2.png"]);
  });

  it("prints --version from package.json", async () => {
    const io = capture();
    const pkg = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
    assert.equal(VERSION, pkg.version);
    assert.equal(await main(["--version"], io), 0);
    assert.deepEqual(io.out, [`nano-banana ${pkg.version}`]);
  });

  it("shows command-specific help", async () => {
    const io = capture();
    assert.equal(await main(["chat", "--help"], io), 0);
    assert.match(io.out.join("\n"), /^Usage: nano-banana chat/);
  });

  it("prints usage to stderr and exits 1 with no command", async () => {
    const io = capture();
    assert.equal(await main([], io), 1);
    assert.match(io.err.join("\n"), /Usage:/);
  });

  it("rejects a missing prompt before creating a client", async () => {
    const io = capture();
    assert.equal(await main(["generate"], io), 1);
    assert.match(io.err.join("\n"), /needs a prompt/);
  });

  it("rejects a missing input image before calling the API", async () => {
    const io = capture();
    let called = false;
    const client = {
      models: {
        generateContent: async () => {
          called = true;
          return okResponse;
        },
      },
    };
    assert.equal(await main(["generate", "edit", "-i", "missing.png"], { ...io, client }), 1);
    assert.match(io.err.join("\n"), /Input image not found: missing\.png/);
    assert.equal(called, false);
  });

  it("reports progress on stderr unless --quiet", async () => {
    const dir = await mkdtemp(path.join(tmpdir(), "nb-quiet-"));
    const client = { models: { generateContent: async () => okResponse } };

    const loud = capture();
    await main(["generate", "a cat", "-o", dir], { ...loud, client });
    assert.match(loud.err.join("\n"), /Generating with/);
    assert.doesNotMatch(loud.out.join("\n"), /Generating with/);

    const quiet = capture();
    await main(["generate", "a cat", "-o", dir, "-q"], { ...quiet, client });
    assert.deepEqual(quiet.err, []);
  });

  it("adds a model hint to 404 errors", async () => {
    const io = capture();
    const client = {
      models: {
        generateContent: async () => {
          throw new ApiError({ message: "not found", status: 404 });
        },
      },
    };
    assert.equal(await main(["generate", "a cat", "-q"], { ...io, client }), 2);
    assert.match(io.err.join("\n"), /GEMINI_IMAGE_MODEL/);
  });

  it("chat keeps going after a blocked turn", async () => {
    const dir = await mkdtemp(path.join(tmpdir(), "nb-chat-blocked-"));
    const replies = [{ promptFeedback: { blockReason: "SAFETY" } }, okResponse];
    const client = { chats: { create: () => ({ sendMessage: async () => replies.shift() }) } };
    const input = Readable.from(["blocked\n", "fine\n", "\n"]);
    const io = capture();

    assert.equal(await main(["chat", "-o", dir], { ...io, client, input }), 0);
    assert.match(io.err.join("\n"), /SAFETY/);
    assert.deepEqual(await readdir(dir), ["turn-2.png"]);
  });
});
