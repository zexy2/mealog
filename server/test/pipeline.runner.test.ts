
import { describe, expect, it, vi } from 'vitest';

import { FixtureVision } from '../src/adapters/vision.fixture';
import {
  ABSTAIN,
  makeMealLog,
  makeNutrients,
  makePerceivedItem,
  type PerceivedItem,
} from '../src/domain/models';
import { load } from '../src/locales/loader';
import { VisionInput, type VisionPort } from '../src/pipeline/ports';
import { CONFIGS, run } from '../src/pipeline/runner';
import { pack_installed, TEST_PACK_ROOT } from './helpers/packs';

const PACK_ROOT = TEST_PACK_ROOT;

// Turkish fixtures and catalogue are licence-restricted; the catalogue is
// installed locally, never committed (docs/licensing.md).
const turkish = pack_installed('tr') ? it : it.skip;

interface StubVision extends VisionPort {
  calls: VisionInput[];
}

function visionStub(
  items: PerceivedItem[],
  order: string[] = [],
  degraded = false,
): StubVision {
  return {
    name: 'handwritten-stub',
    calls: [],
    perceive(input) {
      order.push('perception');
      this.calls.push(input);
      return { observations: items, degraded };
    },
  };
}

describe('pipeline runner', () => {
  it('runs one item end to end through a handwritten VisionPort stub', async () => {
    const vision = visionStub([
      makePerceivedItem({
        surface_form: 'scrambled eggs',
        confidence: 0.95,
      }),
    ]);

    const result = await run(
      vision,
      new VisionInput({ text: 'meal text' }),
      'en_US',
      CONFIGS.V3,
      'runner-single',
    );

    expect(vision.calls).toHaveLength(1);
    expect(result.items).toHaveLength(1);
    expect(result.items[0]).toMatchObject({
      food_id: 'us.eggs_scrambled',
      grams: 100,
      nutrients: { kcal: 149 },
    });
    expect(result.totals.kcal).toBe(149);
    expect(result.action).toBe('review');
    expect(result.degraded).toBe(false);
  });

  turkish('reconciles repeated unknown-count observations into one catalogue default', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({ surface_form: 'ayran', confidence: 1 }),
        makePerceivedItem({ surface_form: 'ayran', confidence: 1 }),
        makePerceivedItem({ surface_form: 'ayran', confidence: 1 }),
        makePerceivedItem({ surface_form: 'ayran', confidence: 1 }),
      ]),
      new VisionInput({ text: 'one glass of ayran' }),
      'tr',
      CONFIGS.V3,
      'runner-duplicate-ayran',
    );

    expect(result.items).toHaveLength(1);
    expect(result.items[0]).toMatchObject({
      food_id: 'tr.ayran',
      quantity: null,
      grams: 200,
      grams_p10: 130,
      grams_p90: 290,
      portion_source: 'catalogue_default',
    });
  });

  turkish('abstains for unsupported chicken meat instead of logging whole egg', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({ surface_form: 'tavuk', portion_hint: '2 parça', count: 2, confidence: 1 }),
      ]),
      new VisionInput({ text: 'tabakta iki parça tavuk' }),
      'tr',
      CONFIGS.V3,
      'runner-chicken-not-egg',
    );

    expect(result.items).toHaveLength(1);
    expect(result.items[0]).toMatchObject({
      query: 'tavuk',
      food_id: ABSTAIN,
      grams: 0,
      grams_p10: 0,
      grams_p90: 0,
    });
    expect(result.totals.kcal).toBe(0);
    expect(result.action).toBe('ask');
  });

  turkish('keeps an unobserved simit count null and unscaled', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({ surface_form: 'simit', portion_hint: 'several', confidence: 1 }),
      ]),
      new VisionInput({ text: 'two stacked simits' }),
      'tr',
      CONFIGS.V3,
      'runner-two-simit-unknown-count',
    );

    expect(result.items[0]).toMatchObject({
      food_id: 'tr.simit',
      quantity: null,
      grams: 100,
      grams_p10: 65,
      grams_p90: 145,
      portion_source: 'catalogue_default',
    });
    expect(result.items[0]?.portion_provenance).toBe('catalogue.default_serving_g=100');
  });

  turkish('sums known counts when duplicate observations carry the same unit', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({ surface_form: 'simit', portion_hint: '1 adet', confidence: 1 }),
        makePerceivedItem({ surface_form: 'simit', portion_hint: '1 adet', confidence: 1 }),
      ]),
      new VisionInput({ text: 'two simits' }),
      'tr',
      CONFIGS.V3,
      'runner-known-count-reconciliation',
    );

    expect(result.items).toHaveLength(1);
    expect(result.items[0]).toMatchObject({
      food_id: 'tr.simit',
      quantity: 2,
      unit: 'adet',
      grams: 200,
    });
  });

  it('keeps repeated submissions on one deterministic portion branch', async () => {
    const results = await Promise.all([
      run(
        visionStub([makePerceivedItem({ surface_form: 'chicken breast', confidence: 1 })]),
        new VisionInput({ text: 'chicken breast' }),
        'en_US',
        CONFIGS.V3,
        'runner-repeat-1',
      ),
      run(
        visionStub([makePerceivedItem({ surface_form: 'chicken breast', portion_hint: 'cup', confidence: 1 })]),
        new VisionInput({ text: 'chicken breast' }),
        'en_US',
        CONFIGS.V3,
        'runner-repeat-2',
      ),
      run(
        visionStub([makePerceivedItem({ surface_form: 'chicken breast', confidence: 1 })]),
        new VisionInput({ text: 'chicken breast' }),
        'en_US',
        CONFIGS.V3,
        'runner-repeat-3',
      ),
    ]);

    expect(results.map((result) => ({
      source: result.items[0]?.portion_source,
      p10: result.items[0]?.grams_p10,
      p90: result.items[0]?.grams_p90,
    }))).toEqual([
      { source: 'catalogue_default', p10: 78, p90: 174 },
      { source: 'catalogue_default', p10: 78, p90: 174 },
      { source: 'catalogue_default', p10: 78, p90: 174 },
    ]);
  });

  turkish('does not reconcile different foods', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({ surface_form: 'simit', confidence: 1 }),
        makePerceivedItem({ surface_form: 'ayran', confidence: 1 }),
      ]),
      new VisionInput({ text: 'simit and ayran' }),
      'tr',
      CONFIGS.V3,
      'runner-different-foods',
    );

    expect(result.items.map((item) => item.food_id)).toEqual(['tr.simit', 'tr.ayran']);
  });

  it('forces a high-confidence fallback result to review', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({
          surface_form: 'scrambled eggs',
          confidence: 1,
          portion_hint: 'one serving',
        }),
      ], [], true),
      new VisionInput({ text: 'meal text' }),
      'en_US',
      CONFIGS.V3,
      'runner-degraded',
    );

    expect(result.items[0]).toMatchObject({
      food_id: 'us.eggs_scrambled',
      confidence: 1,
    });
    expect(result).toMatchObject({ degraded: true, action: 'review' });
  });

  it('keeps a resolver abstention through the end of the meal', async () => {
    const vision = visionStub([
      makePerceivedItem({ surface_form: 'scrambled eggs', confidence: 0.95 }),
      makePerceivedItem({ surface_form: 'unicorn casserole', confidence: 0.95 }),
    ]);

    const result = await run(
      vision,
      new VisionInput({ text: 'meal text' }),
      'en_US',
      CONFIGS.V3,
      'runner-abstain',
    );

    expect(result.items).toHaveLength(2);
    expect(result.items[1]).toMatchObject({
      query: 'unicorn casserole',
      food_id: ABSTAIN,
      grams: 0,
      grams_p10: 0,
      grams_p90: 0,
      nutrients: { kcal: 0, protein_g: 0, carb_g: 0, fat_g: 0 },
    });
    expect(result.totals.kcal).toBe(149);
    expect(result.action).toBe('ask');
    expect(result.question).toContain('unicorn casserole');
  });

  it('routes an empty vision response to ask without inventing an item', async () => {
    const vision = visionStub([]);

    const result = await run(
      vision,
      'fixture-empty',
      'en_US',
      CONFIGS.V3,
      'runner-empty',
    );

    expect(result.items).toEqual([]);
    expect(result.totals.kcal).toBe(0);
    expect(result.action).toBe('ask');
    expect(result.question).toBe('I could not read this meal. What did you eat?');
  });

  it('executes perception before the grounded stages', async () => {
    const order: string[] = [];
    const vision = visionStub([
      makePerceivedItem({ surface_form: 'scrambled eggs', confidence: 0.95 }),
    ], order);

    const result = await run(
      vision,
      new VisionInput({ text: 'meal text' }),
      'en_US',
      CONFIGS.V3,
      'runner-order',
    );

    expect(order).toEqual(['perception']);
    expect(result.items[0]?.food_id).toBe('us.eggs_scrambled');
    expect(result.action).toBe('review');
  });

  it('rejects a separate text argument when input is already a VisionInput', async () => {
    const vision = visionStub([]);

    await expect(run(
      vision,
      new VisionInput({ text: 'meal text' }),
      'en_US',
      CONFIGS.V3,
      'runner-text',
      'duplicate text',
    )).rejects.toThrow('text must be part of VisionInput');
  });

  it('passes the string fixture compatibility path to VisionPort', async () => {
    const vision = visionStub([]);

    await run(vision, 'fixture-id', 'en_US', CONFIGS.V3, 'runner-fixture');

    expect(vision.calls[0]).toMatchObject({
      sampleId: 'fixture-id',
      text: null,
    });
  });

  it('asserts the complete grounded stage order explicitly', async () => {
    vi.resetModules();
    const events: string[] = [];

    vi.doMock('../src/locales/loader', () => ({
      load: vi.fn(() => {
        events.push('load');
        return {
          locale: 'test',
          text_rules: {},
          foods: {
            'test.food': {
              food_id: 'test.food',
              name: 'Test food',
              per_100g: makeNutrients({ kcal: 100 }),
            },
          },
          aliases: {},
          negative_aliases: {},
          units: {},
        };
      }),
    }));
    vi.doMock('../src/pipeline/normalize', () => ({
      fold: vi.fn((text: string) => text),
      normalize: vi.fn((items: PerceivedItem[]) => {
        events.push('normalize');
        return [{ original: items[0], query: 'test food', quantity: null, unit: null }];
      }),
    }));
    vi.doMock('../src/pipeline/retrieval/index', () => ({
      createRetrieval: vi.fn(() => {
        events.push('retrieval_create');
        return {
          search: vi.fn(() => {
            events.push('retrieval');
            return [{ food_id: 'test.food', name: 'Test food', score: 1 }];
          }),
        };
      }),
    }));
    vi.doMock('../src/pipeline/resolve', () => ({
      resolve: vi.fn((query: string, candidates: unknown[]) => {
        events.push('resolve');
        return {
          query,
          food_id: 'test.food',
          candidates,
          grams: 0,
          grams_p10: 0,
          grams_p90: 0,
          confidence: 1,
          nutrients: makeNutrients(),
          portion_source: 'not_applicable',
          portion_provenance: 'not_applicable',
        };
      }),
    }));
    vi.doMock('../src/pipeline/portion', () => ({
      estimate: vi.fn(() => {
        events.push('portion');
        return {
          grams: 100,
          p10: 65,
          p90: 145,
          source: 'catalogue_default',
          provenance: 'test',
        };
      }),
    }));
    vi.doMock('../src/pipeline/nutrition', () => ({
      scalePer100g: vi.fn(() => {
        events.push('nutrition');
        return makeNutrients({ kcal: 100 });
      }),
    }));
    vi.doMock('../src/pipeline/confidence', () => ({
      AUTO_ACCEPT: 0.75,
      route: vi.fn((log: ReturnType<typeof makeMealLog>) => {
        events.push('confidence');
        log.action = 'auto_accept';
        return log;
      }),
    }));

    try {
      const mockedRunner = await import('../src/pipeline/runner');
      const vision = visionStub([makePerceivedItem({ surface_form: 'test food' })], events);
      await mockedRunner.run(
        vision,
        new VisionInput({ text: 'meal text' }),
        'test',
        mockedRunner.CONFIGS.V3,
        'runner-stage-order',
      );

      expect(events).toEqual([
        'retrieval_create',
        'load',
        'perception',
        'normalize',
        'retrieval',
        'resolve',
        'portion',
        'nutrition',
        'confidence',
      ]);
    } finally {
      vi.doUnmock('../src/locales/loader');
      vi.doUnmock('../src/pipeline/normalize');
      vi.doUnmock('../src/pipeline/retrieval/index');
      vi.doUnmock('../src/pipeline/resolve');
      vi.doUnmock('../src/pipeline/portion');
      vi.doUnmock('../src/pipeline/nutrition');
      vi.doUnmock('../src/pipeline/confidence');
      vi.resetModules();
    }
  });

  it('keeps the loader-backed pack available to the runner tests', () => {
    expect(load('en_US', PACK_ROOT).foods['us.eggs_scrambled']).toBeDefined();
  });

  turkish('replays the recorded ayran fallback and routes its uncertainty to review', async () => {
    const result = await run(
      new FixtureVision(),
      'tr_0003',
      'tr',
      CONFIGS.V3,
      'runner-ayran-portion',
    );

    expect(result.items[1]).toMatchObject({
      query: 'ayran',
      food_id: 'tr.ayran',
      grams: 200,
      grams_p10: 150,
      grams_p90: 270,
      confidence: 1,
      quantity: 1,
      unit: 'glass',
      count_origin: 'user_text',
      portion_source: 'catalogue_default_scaled',
      portion_provenance: 'fallback=catalogue.default_serving_g=200; quantity=1; unit=unknown',
    });
    expect(result.action).toBe('review');
  });

  turkish('preserves two simits and one ayran through normalize, resolve, and portion', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({ surface_form: 'simit', portion_hint: 'two pieces', confidence: 1 }),
        makePerceivedItem({ surface_form: 'ayran', portion_hint: 'one serving', confidence: 1 }),
      ]),
      new VisionInput({ text: 'two simits and one ayran' }),
      'tr',
      CONFIGS.V3,
      'runner-multi-instance',
    );

    expect(result.items).toMatchObject([
      {
        food_id: 'tr.simit',
        quantity: 2,
        unit: 'pieces',
        grams: 200,
        grams_p10: 150,
        grams_p90: 270,
      },
      {
        food_id: 'tr.ayran',
        quantity: 1,
        unit: 'serving',
        grams: 200,
        grams_p10: 150,
        grams_p90: 270,
      },
    ]);
    expect(result.totals.kcal).toBe(732);
    expect(result.action).toBe('review');
  });

  turkish('keeps an uncountable provider hint unknown and routes it to review', async () => {
    const result = await run(
      visionStub([
        makePerceivedItem({ surface_form: 'simit', portion_hint: 'several', confidence: 1 }),
      ]),
      new VisionInput({ text: 'several simits' }),
      'tr',
      CONFIGS.V3,
      'runner-unknown-count',
    );

    expect(result.items[0]).toMatchObject({
      food_id: 'tr.simit',
      quantity: null,
      unit: 'several',
      grams: 100,
      grams_p10: 65,
      grams_p90: 145,
    });
    expect(result.action).toBe('review');
  });
});
