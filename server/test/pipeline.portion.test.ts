import { describe, expect, it } from 'vitest';

import type { CanonicalFood } from '../src/domain/models';
import { load } from '../src/locales/loader';
import { pack_installed } from './helpers/packs';
import {
  DEFAULT_SPREAD,
  LABEL_SERVING_SPREAD,
  UNKNOWN_DENSITY_SPREAD,
  estimate,
  parsePortion,
  type PortionLocalePack,
} from '../src/pipeline/portion';

const food = (overrides: Partial<CanonicalFood> = {}): CanonicalFood => ({
  food_id: 'test.food',
  name: 'Test food',
  per_100g: { kcal: 100, protein_g: 1, carb_g: 2, fat_g: 3 },
  default_serving_g: 100,
  default_serving_name: '1 serving',
  source: 'test',
  locale: 'test',
  packaged: false,
  serving_size_g: null,
  serving_size_name: null,
  serving_size_source: null,
  net_weight_g: null,
  net_weight_source: null,
  density_g_per_ml: null,
  density_source: null,
  ...overrides,
});

const pack = (units: PortionLocalePack['units']): PortionLocalePack => ({ units });

const catalogueServingRows = [
  ['tr.lahmacun', 2, 'adet', 280],
  ['tr.yumurta_tavuk', 1, 'adet', 50],
  ['tr.elma', 1, 'adet', 150],
  ['tr.yaprak_sarma', 3, 'adet', 75],
  ['tr.antep_baklavasi', 1, 'dilim', 80],
  ['tr.pilav', 1, 'porsiyon', 180],
  ['tr.ceviz', 1, 'porsiyon', 30],
  ['tr.turk_kahvesi', 1, 'fincan', 7],
  ['tr.simit', 2, 'adet', 200],
  ['tr.ekmek_beyaz', 3, 'dilim', 75],
  ['tr.mercimek_corbasi', 1, 'kase', 250],
] as const;

describe('parsePortion', () => {
  it.each([
    ['1/2 cup', 0.5, 'cup'],
    ['1 1/2 cups', 1.5, 'cups'],
    ['yarım kase', 0.5, 'kase'],
    ['iki kepçe', 2, 'kepçe'],
    ['one and a half cups', 1.5, 'cups'],
  ])('parses %s as %s %s', (hint, quantity, unit) => {
    expect(parsePortion(hint)).toEqual([quantity, unit]);
  });

  it('reports missing quantity instead of inventing measurement evidence', () => {
    expect(parsePortion(undefined)).toEqual([null, null]);
    expect(parsePortion('a serving')).toEqual([null, 'a serving']);
  });
});

// Catalogue-serving rows live in the licence-restricted Turkish pack.
(pack_installed('tr') ? describe : describe.skip)('estimate with the Turkish catalogue', () => {
  it.each(catalogueServingRows)(
    'uses the food catalogue serving for %s %s %s',
    (foodId, quantity, unit, grams) => {
      const trPack = load('tr');
      const result = estimate(trPack.foods[foodId], quantity, unit, trPack);

      expect(result.grams).toBe(grams);
      expect(result.source).toBe('explicit_unit');
      expect(result.provenance).toContain(`per_unit_g=${grams / quantity}`);
      expect(result.provenance).toContain('source=catalogue_serving');
    },
  );

  it('uses one catalogue serving when the matching unit has no quantity', () => {
    const trPack = load('tr');
    const result = estimate(trPack.foods['tr.yaprak_sarma'], null, 'adet', trPack);

    expect(result).toMatchObject({
      grams: 25,
      p10: 16.2,
      p90: 36.2,
      source: 'assumed_unit',
    });
    expect(result.provenance).toContain('per_unit_g=25');
  });

  it('matches catalogue units across accents, case, spaces, and underscores', () => {
    const trPack = load('tr');
    const tea = estimate(trPack.foods['tr.tereyagi'], 1, 'cay_kasigi', trPack);
    const lahmacun = estimate(trPack.foods['tr.lahmacun'], 1, 'ADET', trPack);

    expect(tea).toMatchObject({ grams: 10, source: 'explicit_unit' });
    expect(tea.provenance).toContain('source=catalogue_serving');
    expect(lahmacun).toMatchObject({ grams: 140, source: 'explicit_unit' });
    expect(lahmacun.provenance).toContain('source=catalogue_serving');
  });

  it('falls back to the generic unit table when the food names another unit', () => {
    const result = estimate(
      food({ default_serving_g: 80, default_serving_name: '1 serving' }),
      2,
      'adet',
      pack({ adet: { g: 25 } }),
    );

    expect(result).toMatchObject({
      grams: 50,
      source: 'explicit_unit',
      provenance: 'unit=adet; quantity=2.0; conversion_g=25',
    });
  });

  it('uses a label serving before a provider package-size hint', () => {
    const result = estimate(
      food({
        packaged: true,
        default_serving_g: 999,
        serving_size_g: 170,
        serving_size_name: '1 serving',
        serving_size_source: 'dataset=product-record; field=serving_size',
      }),
      32,
      'oz',
      pack({ oz: { g: 28.35 } }),
    );

    expect(result).toMatchObject({
      grams: 170,
      p10: 153,
      p90: 187,
      source: 'label_serving',
      provenance: 'dataset=product-record; field=serving_size',
    });
    expect(LABEL_SERVING_SPREAD).toEqual([0.9, 1.1]);
  });

  it('uses a sourced net weight for a packaged single-serve food', () => {
    const result = estimate(
      food({
        packaged: true,
        default_serving_g: 999,
        net_weight_g: 250,
        net_weight_source: 'dataset=product-record; field=net_weight',
      }),
      null,
      null,
      pack({}),
    );

    expect(result).toEqual({
      grams: 250,
      p10: 225,
      p90: 275,
      source: 'net_weight',
      provenance: 'dataset=product-record; field=net_weight',
    });
  });

  it('marks a packaged catalogue fallback instead of presenting it as evidence', () => {
    const result = estimate(food({ packaged: true }), null, null, pack({}));

    expect(result).toMatchObject({
      grams: 100,
      source: 'packaged_fallback',
    });
    expect(result.p10).toBe(65);
    expect(result.p90).toBe(145);
    expect(result.provenance).toContain('fallback=catalogue.default_serving_g');
  });

  it('uses food density for a known-density volume, not unit density', () => {
    const result = estimate(
      food({ density_g_per_ml: 0.6583, density_source: 'dataset=USDA; serving basis' }),
      1,
      'cup',
      pack({ cup: { ml: 240 } }),
    );

    expect(result.grams).toBe(158);
    expect(result.p10).toBe(126.4);
    expect(result.p90).toBe(197.5);
    expect(result.source).toBe('known_density');
    expect(result.provenance).toContain('density_source=dataset=USDA; serving basis');
  });

  it('widens a volume estimate when food density is unknown', () => {
    const result = estimate(
      food(),
      2,
      'kepce',
      pack({ kepce: { ml: 150 } }),
    );

    expect(result).toMatchObject({ grams: 300, p10: 135, p90: 525, source: 'unknown_density' });
    expect(UNKNOWN_DENSITY_SPREAD).toEqual([0.45, 1.75]);
  });

  it('keeps the wide unknown-density band when volume quantity is assumed', () => {
    const result = estimate(food(), null, 'kepce', pack({ kepce: { ml: 150 } }));

    expect(result).toMatchObject({ grams: 150, p10: 67.5, p90: 262.5, source: 'unknown_density' });
    expect(result.p10).toBeLessThan(result.grams * DEFAULT_SPREAD[0]);
    expect(result.p90).toBeGreaterThan(result.grams * DEFAULT_SPREAD[1]);
  });

  it('uses mass units and explicit quantity evidence', () => {
    const quantity = parsePortion('1/2 oz')[0];
    const result = estimate(food(), quantity, 'oz', pack({ oz: { g: 28.35 } }));

    expect(result.source).toBe('explicit_unit');
    expect(result.grams).toBe(14.2);
    expect(result.p10).toBe(11.3);
    expect(result.p90).toBe(17.7);
  });

  it('reports catalogue default when quantity and unit are both absent', () => {
    const result = estimate(food({ default_serving_g: 123.4 }), null, null, pack({}));

    expect(result).toEqual({
      grams: 123.4,
      p10: 80.2,
      p90: 178.9,
      source: 'catalogue_default',
      provenance: 'catalogue.default_serving_g=123.4',
    });
  });

  it('scales the catalogue default and marks the unknown-unit fallback', () => {
    const result = estimate(food(), 2, 'unknown-unit', pack({}));

    expect(result).toMatchObject({
      grams: 200,
      p10: 150,
      p90: 270,
      source: 'catalogue_default_scaled',
    });
    expect(result.provenance).toContain('unit=unknown');
  });

  it('keeps a vision count out of explicit-unit provenance', () => {
    const result = estimate(food(), 2, null, pack({}), undefined, 'vision');

    expect(result).toMatchObject({
      grams: 200,
      p10: 150,
      p90: 270,
      source: 'vision_count',
    });
    expect(result.provenance).toContain('count_origin=vision');
    expect(result.source).not.toBe('explicit_unit');
  });
});
