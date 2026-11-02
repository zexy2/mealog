import { Injectable, HttpException, HttpStatus } from '@nestjs/common';

import {
  ABSTAIN,
  makePerceivedItem,
  roundedNutrients,
  type Nutrients,
  type PerceivedItem,
} from '../domain/models';
import { load, type LocalePack } from '../locales/loader';
import { normalize } from '../pipeline/normalize';
import { estimate } from '../pipeline/portion';
import { createRetrieval } from '../pipeline/retrieval/index';
import { resolve } from '../pipeline/resolve';
import { scalePer100g } from '../pipeline/nutrition';

export interface FoodResolveRequest {
  readonly text: string;
  readonly locale: string;
}

export interface FoodResolveCandidate {
  readonly food_id: string;
  readonly name: string;
  readonly score: number;
}

/**
 * The answer to "what is this food called, in the catalogue?".
 *
 * `action` mirrors the meal pipeline: `resolved` carries a `food_id` the client
 * may display, `abstain` carries none and zero nutrients. There is deliberately
 * no third outcome that guesses — the whole point of this endpoint is that the
 * client has somewhere to send a question instead of answering it locally (D1).
 */
export interface FoodResolveResult {
  readonly action: 'resolved' | 'abstain';
  readonly query: string;
  readonly locale: string;
  readonly food_id: string;
  readonly name: string | null;
  readonly candidates: FoodResolveCandidate[];
  readonly confidence: number;
  readonly grams: number;
  readonly grams_p10: number;
  readonly grams_p90: number;
  readonly portion_source: string;
  readonly portion_provenance: string;
  readonly nutrients: Nutrients;
  readonly source_database: string | null;
}

const retrieval = createRetrieval();

/** Free text a person typed, treated as a captured observation. */
function observed(text: string): PerceivedItem {
  return makePerceivedItem({ surface_form: text, confidence: 0.95 });
}

@Injectable()
export class FoodsService {
  resolve(request: FoodResolveRequest): FoodResolveResult {
    const text = request.text.trim();
    if (!text) {
      throw new HttpException({ detail: 'invalid text; a food name is required' },
        HttpStatus.UNPROCESSABLE_ENTITY);
    }

    let pack: LocalePack;
    try {
      pack = load(request.locale);
    } catch (caught) {
      // PackUnavailableError is a 503 and is re-thrown for the global filter;
      // an unknown locale is the caller's mistake.
      if (caught instanceof Error && /no locale pack at|unknown locale/i.test(caught.message)) {
        throw new HttpException(
          { detail: `unsupported or unknown locale '${request.locale}'` },
          HttpStatus.UNPROCESSABLE_ENTITY,
        );
      }
      throw caught;
    }

    // The same normalization, retrieval and closed-set resolution the meal
    // pipeline uses. A name the catalogue cannot hold must abstain here for the
    // same reason it abstains in a photo.
    const [normalized] = normalize([observed(text)], pack, true);
    const query = normalized?.query ?? text;
    const candidates = retrieval.search(query, pack);
    const result = resolve(query, candidates, true);

    const base = {
      query,
      locale: request.locale,
      candidates: result.candidates.map((candidate) => ({
        food_id: candidate.food_id,
        name: candidate.name ?? candidate.food_id,
        score: candidate.score,
      })),
      confidence: result.confidence,
    };

    if (result.food_id === ABSTAIN) {
      // A missing catalogue food is not a zero-calorie food, and it is not a
      // near-miss food either: no portions, no nutrition, no invented name.
      return {
        ...base,
        action: 'abstain',
        food_id: ABSTAIN,
        name: null,
        grams: 0,
        grams_p10: 0,
        grams_p90: 0,
        portion_source: 'none',
        portion_provenance: 'catalogue_abstain',
        nutrients: roundedNutrients(
          scalePer100g({ kcal: 0, protein_g: 0, carb_g: 0, fat_g: 0 }, 0),
        ),
        source_database: null,
      };
    }

    const food = pack.foods[result.food_id];
    const portion = estimate(food, result.quantity, null, pack);

    return {
      ...base,
      action: 'resolved',
      food_id: result.food_id,
      name: food.name,
      grams: portion.grams,
      grams_p10: portion.p10,
      grams_p90: portion.p90,
      portion_source: portion.source,
      portion_provenance: portion.provenance,
      nutrients: roundedNutrients(scalePer100g(food.per_100g, portion.grams)),
      source_database: food.source ?? null,
    };
  }
}
