## Using Nano Banana with JavaScript

Guide on how to use Nano Banana aka Gemini 2.5 Flash Image in JavaScript with the [Google GenAI JS/TS SDK](https://github.com/googleapis/js-genai).

More resources:

- Get an API key from [Google AI Studio](https://aistudio.google.com/apikey).
- [Nano Banana Gemini API docs](https://ai.google.dev/gemini-api/docs/image-generation)
- Prefer something you can run straight away? The [`javascript/`](./javascript/) folder has a
  tested command-line version of every snippet below.

The snippets read your key from the `GEMINI_API_KEY` environment variable, so it never ends up in
your source code. Export it in your shell, or put it in a `.env` file and run the scripts with
`node --env-file=.env script.mjs` (Node.js 20.6+).

## Installation

Install the SDK

```bash
npm install @google/genai
```

When using TypeScript also install TypeScript definitions for node

```bash
npm install --save-dev @types/node
```

## Image Generation from Text

```ts
import { GoogleGenAI } from "@google/genai";
import * as fs from "node:fs";

// The original "gemini-2.5-flash-image-preview" model ID has been retired.
const MODEL = process.env.GEMINI_IMAGE_MODEL ?? "gemini-2.5-flash-image";

async function main() {

  const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

  const prompt =
    "Create a photorealistic image of an orange cat with green eyes, sitting on a couch.";

  const response = await ai.models.generateContent({
    model: MODEL,
    contents: prompt,
  });
  for (const part of response.candidates?.[0]?.content?.parts ?? []) {
    if (part.text) {
      console.log(part.text);
    } else if (part.inlineData) {
      const imageData = part.inlineData.data;
      const buffer = Buffer.from(imageData, "base64");
      fs.writeFileSync("cat.png", buffer);
    }
  }
}

main();
```

## Image Editing with Text and Image Inputs

```ts
import { GoogleGenAI } from "@google/genai";
import * as fs from "node:fs";

// The original "gemini-2.5-flash-image-preview" model ID has been retired.
const MODEL = process.env.GEMINI_IMAGE_MODEL ?? "gemini-2.5-flash-image";

async function main() {

  const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

  const imageData = fs.readFileSync("cat.png");
  const base64Image = imageData.toString("base64");

  const prompt = [
    { text:   `Using the image of the cat, create a photorealistic,
street-level view of the cat walking along a sidewalk in a
New York City neighborhood, with the blurred legs of pedestrians
and yellow cabs passing by in the background.` },
    {
      inlineData: {
        mimeType: "image/png",
        data: base64Image,
      },
    },
  ];

  const response = await ai.models.generateContent({
    model: MODEL,
    contents: prompt,
  });
  for (const part of response.candidates?.[0]?.content?.parts ?? []) {
    if (part.text) {
      console.log(part.text);
    } else if (part.inlineData) {
      const imageData = part.inlineData.data;
      const buffer = Buffer.from(imageData, "base64");
      fs.writeFileSync("cat2.png", buffer);
    }
  }
}

main();
```

## Photo restoration with Nano Banana

```ts
import { GoogleGenAI } from "@google/genai";
import * as fs from "node:fs";

// The original "gemini-2.5-flash-image-preview" model ID has been retired.
const MODEL = process.env.GEMINI_IMAGE_MODEL ?? "gemini-2.5-flash-image";

async function main() {

  const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

  const imageData = fs.readFileSync("lunch.jpg"); // "Lunch atop a Skyscraper, 1932"
  const base64Image = imageData.toString("base64");

  const prompt = [
    { text: "Restore and colorize this image from 1932" },
    {
      inlineData: {
        mimeType: "image/jpeg", // must match the input file's format
        data: base64Image,
      },
    },
  ];

  const response = await ai.models.generateContent({
    model: MODEL,
    contents: prompt,
  });
  for (const part of response.candidates?.[0]?.content?.parts ?? []) {
    if (part.text) {
      console.log(part.text);
    } else if (part.inlineData) {
      const imageData = part.inlineData.data;
      const buffer = Buffer.from(imageData, "base64");
      fs.writeFileSync("lunch-restored.png", buffer);
    }
  }
}

main();
```

## Working with Multiple Input Images

```ts
import { GoogleGenAI } from "@google/genai";
import * as fs from "node:fs";

// The original "gemini-2.5-flash-image-preview" model ID has been retired.
const MODEL = process.env.GEMINI_IMAGE_MODEL ?? "gemini-2.5-flash-image";

async function main() {

  const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

  const imageData1 = fs.readFileSync("girl.png");
  const base64Image1 = imageData1.toString("base64");
  
  const imageData2 = fs.readFileSync("tshirt.png");
  const base64Image2 = imageData2.toString("base64");

  const prompt = [
    { text: "Make the girl wear this t-shirt. Leave the background unchanged." },
    {
      inlineData: {
        mimeType: "image/png",
        data: base64Image1,
      },
    },
    {
      inlineData: {
        mimeType: "image/png",
        data: base64Image2,
      },
    },
  ];

  const response = await ai.models.generateContent({
    model: MODEL,
    contents: prompt,
  });
  for (const part of response.candidates?.[0]?.content?.parts ?? []) {
    if (part.text) {
      console.log(part.text);
    } else if (part.inlineData) {
      const imageData = part.inlineData.data;
      const buffer = Buffer.from(imageData, "base64");
      fs.writeFileSync("girl-with-tshirt.png", buffer);
    }
  }
}

main();
```

## Conversational Image Editing

```ts
import { GoogleGenAI } from "@google/genai";
import * as fs from "node:fs";

// The original "gemini-2.5-flash-image-preview" model ID has been retired.
const MODEL = process.env.GEMINI_IMAGE_MODEL ?? "gemini-2.5-flash-image";

async function main() {

  const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

  const chat = ai.chats.create({model: MODEL});
  
  const imageData = fs.readFileSync("cat.png");
  const base64Image = imageData.toString("base64");

  const response1 = await chat.sendMessage({
    message: [
      { text: "Change the cat to a bengal cat, leave everything else the same." },
      {
        inlineData: {
          mimeType: "image/png",
          data: base64Image,
        },
      },
    ]
  });
  saveImages(response1, "bengal-cat");

  const response2 = await chat.sendMessage({
    message: "The cat should wear a funny party hat"
  });
  saveImages(response2, "bengal-cat-party-hat");
}

// Write every image in a response to <name>-<n>.png
function saveImages(response, name) {
  const parts = response.candidates?.[0]?.content?.parts ?? [];
  parts
    .filter((part) => part.inlineData?.data)
    .forEach((part, i) => {
      fs.writeFileSync(`${name}-${i + 1}.png`, Buffer.from(part.inlineData.data, "base64"));
    });
}

main();
```