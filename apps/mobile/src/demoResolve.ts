import type { FoodResolution } from "./api";

/**
 * Demo-mode answers for "what is this food?".
 *
 * The live client never resolves a name itself — it asks
 * `POST /v1/foods/resolve` (D1). Demo mode has no server to ask, so this file
 * answers from a small, fixed demo catalogue whose provenance says so in every
 * field: `source_database` is `DEMO`, never `TURKOMP`, and a name outside the
 * demo catalogue abstains rather than being guessed at.
 *
 * Keep this list short and boring. It exists so the demo flow has something to
 * add to a plate, not to model the world.
 */
type DemoFood = {
  food_id: string;
  name: string;
  kcal: number;
  protein_g: number;
  carb_g: number;
  fat_g: number;
  grams: number;
};

const DEMO_FOODS: readonly DemoFood[] = [
  { food_id: "tr.simit", name: "Simit", kcal: 329, protein_g: 9.5, carb_g: 57, fat_g: 6.6, grams: 100 },
  { food_id: "tr.pilav", name: "Pirinç pilavı", kcal: 272, protein_g: 5.4, carb_g: 50.4, fat_g: 5.6, grams: 180 },
  { food_id: "tr.mercimek_corbasi", name: "Mercimek çorbası", kcal: 155, protein_g: 7.8, carb_g: 23.5, fat_g: 3.5, grams: 250 },
  { food_id: "tr.kuru_fasulye", name: "Kuru fasulye (etli)", kcal: 295, protein_g: 17.2, carb_g: 33, fat_g: 10.8, grams: 250 },
  { food_id: "tr.ayran", name: "Ayran", kcal: 74, protein_g: 3.4, carb_g: 5.2, fat_g: 4, grams: 200 },
  { food_id: "tr.ekmek_beyaz", name: "Ekmek, beyaz", kcal: 138, protein_g: 4.7, carb_g: 25, fat_g: 1.6, grams: 50 },
  { food_id: "tr.menemen", name: "Menemen", kcal: 260, protein_g: 13.6, carb_g: 10.6, fat_g: 18.3, grams: 220 },
  { food_id: "tr.lahmacun", name: "Lahmacun", kcal: 340, protein_g: 14.7, carb_g: 47.6, fat_g: 10.4, grams: 140 },
  { food_id: "tr.coban_salatasi", name: "Çoban Salatası", kcal: 68, protein_g: 1.8, carb_g: 6.8, fat_g: 3.8, grams: 150 },
];

const DEMO_ABSTENTION = (query: string, candidates: FoodResolution["candidates"] = []): FoodResolution => ({
  action: "abstain",
  query,
  locale: "tr",
  food_id: "ABSTAIN",
  name: null,
  candidates,
  confidence: 0,
  grams: 0,
  grams_p10: 0,
  grams_p90: 0,
  portion_source: "none",
  portion_provenance: "catalogue_abstain",
  nutrients: { kcal: 0, protein_g: 0, carb_g: 0, fat_g: 0 },
  source_database: null,
});

export function resolveDemoFood(text: string): FoodResolution {
  const query = text.trim();
  const lower = query.toLocaleLowerCase("tr");
  const match = DEMO_FOODS.find((food) => {
    const name = food.name.toLocaleLowerCase("tr");
    return name === lower || name.includes(lower) || lower.includes(name);
  });

  if (!match) {
    // The demo catalogue is deliberately small, so a miss is common and is
    // shown as such. Guessing from substrings ("burger" -> "köfte") was the
    // exact behaviour this replaced.
    return DEMO_ABSTENTION(query);
  }

  const ratio = match.grams / 100;
  return {
    action: "resolved",
    query,
    locale: "tr",
    food_id: match.food_id,
    name: match.name,
    candidates: [{ food_id: match.food_id, name: match.name, score: 1 }],
    confidence: 0.95,
    grams: match.grams,
    grams_p10: Math.round(match.grams * 0.8),
    grams_p90: Math.round(match.grams * 1.2),
    portion_source: "demo_catalogue",
    portion_provenance: "demo_catalogue_portion",
    nutrients: {
      kcal: Math.round(match.kcal * ratio),
      protein_g: Math.round(match.protein_g * ratio * 10) / 10,
      carb_g: Math.round(match.carb_g * ratio * 10) / 10,
      fat_g: Math.round(match.fat_g * ratio * 10) / 10,
    },
    source_database: "DEMO",
  };
}
