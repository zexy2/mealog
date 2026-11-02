import 'reflect-metadata';

import { Test } from '@nestjs/testing';
import type { NestExpressApplication } from '@nestjs/platform-express';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { AppModule } from '../src/app/app.module';
import type { MealLog } from '../src/domain/models';
import { configureBodyParsers } from '../src/main';
import { pack_installed } from './helpers/packs';

// The Turkish catalogue is installed locally, never committed.
const turkish = pack_installed('tr') ? describe : describe.skip;

turkish('POST /v1/meals/correct', () => {
  let app: NestExpressApplication;

  beforeAll(async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = moduleRef.createNestApplication<NestExpressApplication>({ bodyParser: false });
    configureBodyParsers(app);
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
  });

  it('recalculates a count correction and ignores client nutrient values', async () => {
    const initial = await request(app.getHttpServer())
      .post('/v1/meals')
      .send({ idempotency_key: 'correction-http-count', sample_id: 'tr_0002', locale: 'tr', config: 'V3' });
    expect(initial.status).toBe(200);
    const initialMeal = initial.body as unknown as MealLog;
    expect(initialMeal).toMatchObject({ action: 'review' });
    expect(initialMeal.items[0]).toMatchObject({
      food_id: 'tr.simit',
      quantity: null,
      count_origin: 'vision',
      portion_source: 'catalogue_default',
    });

    const tampered = structuredClone(initialMeal) as unknown as Record<string, unknown>;
    const item = (tampered.items as Array<Record<string, unknown>>)[0];
    item.nutrients = { kcal: 99999, protein_g: 99999, carb_g: 99999, fat_g: 99999 };
    item.grams = 99999;
    tampered.totals = { kcal: 99999, protein_g: 99999, carb_g: 99999, fat_g: 99999 };

    const corrected = await request(app.getHttpServer())
      .post('/v1/meals/correct')
      .send({ meal: tampered, corrections: [{ item_index: 0, quantity: 2, unit: 'adet' }] });

    expect(corrected.status).toBe(200);
    const correctedMeal = corrected.body as unknown as MealLog;
    expect(correctedMeal.items[0]).toMatchObject({
      food_id: 'tr.simit',
      quantity: 2,
      unit: 'adet',
      grams: 200,
      grams_p10: 160,
      grams_p90: 250,
      nutrients: { kcal: 658 },
    });
    expect(correctedMeal.items[0]?.portion_provenance).toContain('user_confirmed');
    expect(correctedMeal.totals.kcal).toBe(658);
  });

  it('keeps an unknown count in Review when the user says not sure', async () => {
    const initial = await request(app.getHttpServer())
      .post('/v1/meals')
      .send({ idempotency_key: 'correction-http-unknown', sample_id: 'tr_0002', locale: 'tr', config: 'V3' });

    const corrected = await request(app.getHttpServer())
      .post('/v1/meals/correct')
      .send({
        meal: initial.body as unknown as MealLog,
        corrections: [{ item_index: 0, quantity: null, unit: 'adet' }],
      });

    expect(corrected.status).toBe(200);
    const correctedMeal = corrected.body as unknown as MealLog;
    expect(correctedMeal).toMatchObject({ action: 'review' });
    expect(correctedMeal.items[0]).toMatchObject({ quantity: null, grams: 100, grams_p10: 65, grams_p90: 145 });
  });
});
