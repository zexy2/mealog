import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

// The mobile client must not hold a nutrition table of its own (D1).
//
// `screens/Review.tsx` used to carry `TURKISH_FOOD_NUTRITION_MAP` — eleven foods
// with per-100g values — and `App.tsx` multiplied them into a "resolved" item
// without asking the server. That is the client asserting catalogue truth with
// none of the catalogue's guards, and it answered `burger` with a 350 kcal plate
// the catalogue does not contain. The server now answers those questions at
// `POST /v1/foods/resolve`; these assertions keep the table from coming back.

const mobileSources = [
  ["App.tsx", readFileSync(new URL("../App.tsx", import.meta.url), "utf8")],
  ...["Review.tsx", "Abstention.tsx", "Day.tsx", "Capture.tsx"].map((name) => [
    `screens/${name}`,
    readFileSync(new URL(`../screens/${name}`, import.meta.url), "utf8"),
  ]),
];

for (const [file, source] of mobileSources) {
  assert.equal(
    source.includes("TURKISH_FOOD_NUTRITION_MAP"),
    false,
    `${file} must not carry a client-side nutrition table`,
  );
  assert.equal(
    source.includes("kcal_per_100g"),
    false,
    `${file} must not hold per-100g nutrient values`,
  );
}

// A nutrient literal is a *non-zero* number assigned to a nutrition field. Zero
// is the collapse case (the server sent no mass, so nothing is rescaled), not an
// assertion about food; the user's own manual calories are the other legitimate
// case because that number is theirs.
const NUTRIENT_LITERAL = /\b(protein_g|carbs?|carb_g|fat_g|kcal|calories)\s*:\s*[1-9]\d*/;
const reviewSource = readFileSync(new URL("../screens/Review.tsx", import.meta.url), "utf8");
for (const line of reviewSource.split("\n")) {
  const isUserInput = /manual_user_input|USER_CUSTOM|İptal|manüel|Manuel/i.test(line);
  if (isUserInput) continue;
  assert.equal(
    NUTRIENT_LITERAL.test(line),
    false,
    `screens/Review.tsx holds a nutrient literal outside manual entry: ${line.trim()}`,
  );
}

// The food id of a catalogue row is the server's to choose. The client may
// reference ids it received, but it must not invent one for a lookup.
const HARDCODED_FOOD_ID = /["']tr\.(pizza|kofte_izgara|patates|manti|coban_salatasi|ayran|ekmek_beyaz|mercimek_corbasi|pilav|kuru_fasulye)["']/;
const appSource = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
assert.equal(
  HARDCODED_FOOD_ID.test(appSource),
  false,
  "App.tsx must not map free text to a food_id itself; ask /v1/foods/resolve",
);
assert.equal(
  /lower\.includes\("(burger|pizza|patates|salata|ayran|ekmek|corba|pilav|fasulye)"\)/.test(appSource),
  false,
  "App.tsx must not guess a catalogue row from a substring of the typed name",
);
