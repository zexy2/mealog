import 'reflect-metadata';

import { Test } from '@nestjs/testing';
import type { NestExpressApplication } from '@nestjs/platform-express';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { AppModule } from '../src/app/app.module';
import { configureBodyParsers } from '../src/main';
import { pack_installed } from './helpers/packs';

// `POST /v1/foods/resolve` is how the mobile client asks the catalogue a
// question instead of guessing locally (D1). The Turkish assertions need the
// restricted catalogue, so they skip by name without it.
const turkish = pack_installed('tr') ? it : it.skip;

interface ResolveBody {
  action: 'resolved' | 'abstain';
  locale: string;
  food_id: string;
  name: string | null;
  candidates: { food_id: string; name: string; score: number }[];
  confidence: number;
  grams: number;
  grams_p10: number;
  grams_p90: number;
  nutrients: { kcal: number; protein_g: number; carb_g: number; fat_g: number };
  source_database: string | null;
}

function body(response: { body: unknown }): ResolveBody {
  return response.body as ResolveBody;
}

describe('POST /v1/foods/resolve', () => {
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

  turkish('returns a catalogue item with server-computed nutrition', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: 'simit', locale: 'tr' })
      .expect(200);

    expect(body(response).action).toBe('resolved');
    expect(body(response).food_id).toBe('tr.simit');
    expect(body(response).grams).toBeGreaterThan(0);
    // Nutrition comes from the catalogue, scaled by the portion stage. The
    // client is never asked to multiply per-100g values itself.
    expect(body(response).nutrients.kcal).toBeGreaterThan(0);
    expect(body(response).source_database).toBeTruthy();
  });

  turkish('resolves through the locale normalizer, not a substring match', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: 'Pirinç pilavı', locale: 'tr' })
      .expect(200);

    expect(body(response).food_id).toBe('tr.pilav');
  });

  turkish('abstains instead of inventing a food outside the catalogue', async () => {
    // The mobile shadow map answered `burger` with `tr.kofte_izgara` and an
    // invented 350 kcal. The catalogue has no burger; the honest answer is an
    // abstention the UI can render as "not in the catalogue".
    const response = await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: 'tofu', locale: 'tr' })
      .expect(200);

    expect(body(response).action).toBe('abstain');
    expect(body(response).food_id).toBe('ABSTAIN');
    expect(body(response).nutrients.kcal).toBe(0);
    expect(body(response).candidates.length).toBeGreaterThanOrEqual(0);
  });

  it('rejects an empty query rather than searching for nothing', async () => {
    await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: '   ', locale: 'en_US' })
      .expect(422);
  });

  it('falls back to the configured default locale, and says which one it used', async () => {
    // Omitting the locale is not an error: the deployment has a default. What
    // matters is that the answer names the locale it was resolved in, so a
    // client cannot silently mix packs.
    const response = await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: 'scrambled eggs' })
      .expect(200);

    expect(body(response).locale).toBe('en_US');
    expect(body(response).food_id).toBe('us.eggs_scrambled');
  });

  it('reports an unknown locale as an unprocessable request', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: 'eggs', locale: 'xx_YY' })
      .expect(422);

    expect((response.body as { detail: string }).detail).toMatch(/locale/i);
  });

  it('serves a locale whose catalogue is not installed as 503', async () => {
    // `tr` is defined but its rows are licence-restricted and not distributed.
    if (pack_installed('tr')) return;
    const response = await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: 'simit', locale: 'tr' })
      .expect(503);

    expect((response.body as { locale: string }).locale).toBe('tr');
  });

  it('resolves a shipped locale', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/foods/resolve')
      .send({ text: 'scrambled eggs', locale: 'en_US' })
      .expect(200);

    expect(body(response).action).toBe('resolved');
    expect(body(response).food_id).toBe('us.eggs_scrambled');
  });
});
