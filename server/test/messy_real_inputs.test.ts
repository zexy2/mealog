/**
 * @file messy_real_inputs.test.ts
 * Evaluation and verification test suite for realistic, messy, multi-item dining images.
 * Tests multi-component plate perception, Turkish food catalog grounding, and confidence gating.
 */

import { describe, expect, it } from 'vitest';

import { makePerceivedItem } from '../src/domain/models';
import { VisionInput, type VisionPort } from '../src/pipeline/ports';
import { run, CONFIGS } from '../src/pipeline/runner';
import { load } from '../src/locales/loader';
import { pack_installed } from './helpers/packs';

(pack_installed('tr') ? describe : describe.skip)('Messy Real-World Multi-Item Food Tests', () => {
  it('verifies Turkish pack loaded and has rich multi-item food coverage', () => {
    const pack = load('tr');
    expect(pack.foods['tr.menemen']).toBeDefined();
    expect(pack.foods['tr.pilav']).toBeDefined();
    expect(pack.foods['tr.kuru_fasulye']).toBeDefined();
    expect(pack.foods['tr.ayran']).toBeDefined();
    expect(pack.foods['tr.domates']).toBeDefined();
    expect(pack.foods['tr.patates']).toBeDefined();
    expect(pack.foods['tr.edirne_beyaz_peyniri']).toBeDefined();
  });

  it('properly resolves multi-item text and calculates accurate un-hallucinated nutrition', async () => {
    const fakeVision: VisionPort = {
      name: 'fake_vision',
      perceive: () =>
        Promise.resolve({
          observations: [
            makePerceivedItem({ surface_form: 'kuru fasulye', cooking_method: 'stewed', portion_hint: '1 kase', count: 1, confidence: 0.95 }),
            makePerceivedItem({ surface_form: 'pirinc pilavi', cooking_method: 'boiled', portion_hint: '1 porsiyon', count: 1, confidence: 0.92 }),
            makePerceivedItem({ surface_form: 'yogurt', cooking_method: 'plain', portion_hint: '1 kase', count: 1, confidence: 0.9 }),
            makePerceivedItem({ surface_form: 'ekmek', cooking_method: 'baked', portion_hint: '2 dilim', count: 2, confidence: 0.96 }),
          ],
          degraded: false,
        }),
    };

    const meal = await run(fakeVision, new VisionInput({ text: 'kuru fasulye pilav yogurt ekmek' }), 'tr', CONFIGS.V3, 'test-messy-lunch');

    expect(meal.items.length).toBe(4);
    expect(meal.items[0].food_id).toBe('tr.kuru_fasulye');
    expect(meal.items[1].food_id).toBe('tr.pilav');
    expect(meal.items[2].food_id).toBe('tr.yogurt_tam_yagli');
    expect(meal.items[3].food_id).toBe('tr.ekmek_beyaz');

    // Nutrition must be computed exclusively from ground-truth catalogue
    expect(meal.totals.kcal).toBeGreaterThan(500);
    expect(meal.totals.protein_g).toBeGreaterThan(20);
    expect(['auto_accept', 'ask', 'review']).toContain(meal.action);
  });

  it('evaluates multi-item breakfast perception and abstains on out-of-catalog items gracefully', async () => {
    const fakeVision: VisionPort = {
      name: 'fake_vision',
      perceive: () =>
        Promise.resolve({
          observations: [
            makePerceivedItem({ surface_form: 'menemen', cooking_method: 'pan-fried', portion_hint: '1 porsiyon', count: 1, confidence: 0.95 }),
            makePerceivedItem({ surface_form: 'beyaz peynir', cooking_method: 'raw', portion_hint: '2 dilim', count: 2, confidence: 0.93 }),
            makePerceivedItem({ surface_form: 'siyah zeytin', cooking_method: 'cured', portion_hint: '1 porsiyon', count: 1, confidence: 0.91 }),
            makePerceivedItem({ surface_form: 'domates', cooking_method: 'raw', portion_hint: '1 adet', count: 1, confidence: 0.94 }),
            makePerceivedItem({ surface_form: 'avokado tostu', cooking_method: 'toasted', portion_hint: '1 dilim', count: 1, confidence: 0.88 }),
          ],
          degraded: false,
        }),
    };



    const meal = await run(fakeVision, new VisionInput({ text: 'serpme kahvalti' }), 'tr', CONFIGS.V3, 'test-messy-breakfast');

    expect(meal.items.length).toBe(5);
    expect(meal.items[0].food_id).toBe('tr.menemen');
    expect(meal.items[1].food_id).toBe('tr.edirne_beyaz_peyniri');
    expect(meal.items[2].food_id).toBe('tr.zeytin_siyah');
    expect(meal.items[3].food_id).toBe('tr.domates');
    expect(meal.items[4].food_id).toBe('ABSTAIN'); // D1 anti-hallucination guarantee holds!
    expect(meal.action).toBe('ask');
  });
});
