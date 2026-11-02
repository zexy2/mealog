import { describe, expect, it } from 'vitest';

import { ABSTAIN, makeResolvedItem } from '../src/domain/models';
import { load } from '../src/locales/loader';
import { clarificationFor } from '../src/pipeline/clarification';
import { pack_installed } from './helpers/packs';

// The Turkish catalogue is installed locally and never committed; without it
// the block skips instead of failing the whole file at import time.
const pack = pack_installed('tr') ? load('tr') : (null as never);

(pack_installed('tr') ? describe : describe.skip)('item-scoped clarification metadata', () => {
  it('asks for a count only when the catalogue has a countable serving', () => {
    const item = makeResolvedItem({
      query: 'simit',
      food_id: 'tr.simit',
      confidence: 1,
      quantity: null,
      unit: 'several',
      grams: 100,
      grams_p10: 65,
      grams_p90: 145,
    });

    expect(clarificationFor(item, pack)).toEqual({
      kind: 'count',
      unit: 'adet',
      options: [1, 2, 3, null],
    });
  });

  it('asks for portion evidence rather than count on a serving food', () => {
    const item = makeResolvedItem({
      query: 'pilav',
      food_id: 'tr.pilav',
      confidence: 1,
      quantity: 1,
      unit: 'porsiyon',
      grams: 180,
      grams_p10: 135,
      grams_p90: 243,
    });

    expect(clarificationFor(item, pack)).toEqual({ kind: 'portion', unit: null, options: [] });
  });

  it('does not show count choices when identity is the uncertain dimension', () => {
    const item = makeResolvedItem({
      query: 'simit',
      food_id: 'tr.simit',
      candidates: [
        { food_id: 'tr.simit', name: 'Simit', score: 0.5 },
        { food_id: 'tr.ekmek_beyaz', name: 'Ekmek', score: 0.49 },
      ],
      confidence: 0.5,
      quantity: null,
      grams: 100,
      grams_p10: 65,
      grams_p90: 145,
    });

    expect(clarificationFor(item, pack)).toEqual({ kind: 'identity', unit: null, options: [] });
  });

  it('keeps an abstention explicit while exposing candidates for manual selection', () => {
    const item = makeResolvedItem({
      query: 'unknown',
      food_id: ABSTAIN,
      candidates: [{ food_id: 'tr.simit', name: 'Simit', score: 0.7 }],
    });

    expect(clarificationFor(item, pack)).toEqual({ kind: 'identity', unit: null, options: [] });
  });
});
