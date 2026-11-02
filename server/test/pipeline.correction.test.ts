import { describe, expect, it } from 'vitest';

import {
  makeMealLog,
  makeNutrients,
  makeResolvedItem,
} from '../src/domain/models';
import { applyCorrections, CorrectionValidationError } from '../src/pipeline/correction';
import { pack_installed } from './helpers/packs';

// Corrections resolve against the Turkish catalogue, which is installed
// locally and never committed (docs/licensing.md).
const turkish = pack_installed('tr') ? describe : describe.skip;

function meal() {
  return makeMealLog({
    idempotency_key: 'correction-test',
    locale: 'tr',
    config: 'V3',
    items: [
      makeResolvedItem({
        query: 'simit',
        food_id: 'tr.simit',
        candidates: [{ food_id: 'tr.simit', name: 'Simit', score: 1 }],
        quantity: null,
        unit: 'several',
        grams: 100,
        grams_p10: 65,
        grams_p90: 145,
        confidence: 1,
        nutrients: makeNutrients({ kcal: 329 }),
      }),
      makeResolvedItem({
        query: 'ayran',
        food_id: 'tr.ayran',
        candidates: [{ food_id: 'tr.ayran', name: 'Ayran', score: 1 }],
        quantity: 1,
        unit: 'serving',
        grams: 200,
        grams_p10: 150,
        grams_p90: 270,
        confidence: 1,
        nutrients: makeNutrients({ kcal: 74 }),
      }),
    ],
  });
}

function mealWithAbstain() {
  const result = meal();
  result.items.push(makeResolvedItem({
    query: 'unknown',
    food_id: 'ABSTAIN',
    candidates: [{ food_id: 'tr.simit', name: 'Simit', score: 0.1 }],
    grams: 0,
    grams_p10: 0,
    grams_p90: 0,
    nutrients: makeNutrients(),
  }));
  return result;
}

turkish('server-side meal correction', () => {
  it('recomputes count, band, nutrients and totals while preserving ayran', () => {
    const result = applyCorrections({
      meal: meal(),
      corrections: [{ item_index: 0, quantity: 2, unit: 'adet' }],
    });

    expect(result.items[0]).toMatchObject({
      food_id: 'tr.simit',
      quantity: 2,
      unit: 'adet',
      grams: 200,
      grams_p10: 160,
      grams_p90: 250,
      nutrients: { kcal: 658 },
    });
    expect(result.items[0].portion_provenance).toContain('correction=quantity=user_confirmed,unit=user_confirmed');
    expect(result.items[1]).toMatchObject({
      food_id: 'tr.ayran',
      quantity: 1,
      grams: 200,
      grams_p10: 150,
      grams_p90: 270,
    });
    expect(result.totals).toEqual({
      kcal: result.items[0].nutrients.kcal + result.items[1].nutrients.kcal,
      protein_g: result.items[0].nutrients.protein_g + result.items[1].nutrients.protein_g,
      carb_g: result.items[0].nutrients.carb_g + result.items[1].nutrients.carb_g,
      fat_g: result.items[0].nutrients.fat_g + result.items[1].nutrients.fat_g,
    });
    expect(result.action).toBe('review');
  });

  it('keeps an explicit not-sure count unknown and in Review', () => {
    const result = applyCorrections({
      meal: meal(),
      corrections: [{ item_index: 0, quantity: null, unit: 'adet' }],
    });

    expect(result.items[0]).toMatchObject({
      quantity: null,
      unit: 'adet',
      grams: 100,
      grams_p10: 65,
      grams_p90: 145,
    });
    expect(result.items[0].portion_provenance).toContain('correction=quantity=user_confirmed,unit=user_confirmed');
    expect(result.action).toBe('review');
  });

  it('keeps a degraded corrected meal in Review', () => {
    const input = meal();
    input.degraded = true;

    const result = applyCorrections({
      meal: input,
      corrections: [{ item_index: 0, quantity: 2, unit: 'adet' }],
    });

    expect(result.degraded).toBe(true);
    expect(result.action).toBe('review');
  });

  it('uses the existing range for a user gram correction', () => {
    const result = applyCorrections({
      meal: meal(),
      corrections: [{ item_index: 0, grams: 120 }],
    });

    expect(result.items[0]).toMatchObject({
      grams: 120,
      grams_p10: 96,
      grams_p90: 150,
      portion_source: 'explicit_unit',
    });
    expect(result.items[0].portion_provenance).toContain('correction=grams=user_confirmed');
  });

  it('rejects a food outside the locale catalogue', () => {
    expect(() => applyCorrections({
      meal: meal(),
      corrections: [{ item_index: 0, food_id: 'tr.invented_food' }],
    })).toThrowError(new CorrectionValidationError("unknown food_id 'tr.invented_food'"));
  });

  it('does not trust client nutrient or gram values', () => {
    const input = mealWithAbstain();
    input.items[0].nutrients = makeNutrients({ kcal: 99999 });
    input.items[0].grams = 99999;
    input.items[2].nutrients = makeNutrients({ kcal: 99999 });
    input.items[2].grams = 99999;
    input.items[2].grams_p10 = 99999;
    input.items[2].grams_p90 = 99999;
    input.totals = makeNutrients({ kcal: 99999 });

    const result = applyCorrections({ meal: input, corrections: [] });

    expect(result.items[0].nutrients.kcal).toBe(329);
    expect(result.items[0].grams).toBe(100);
    expect(result.items[2].nutrients).toEqual(makeNutrients());
    expect(result.items[2].grams).toBe(0);
    expect(result.totals.kcal).not.toBe(99999);
  });
});
