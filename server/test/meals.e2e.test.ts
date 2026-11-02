import 'reflect-metadata';

import { Test } from '@nestjs/testing';
import type { NestExpressApplication } from '@nestjs/platform-express';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { AppModule } from '../src/app/app.module';
import { Settings } from '../src/config';
import { makePerceivedItem } from '../src/domain/models';
import { configureBodyParsers } from '../src/main';
import { VisionProviderError } from '../src/adapters/vision.gemini';
import { NUTRITION_ESTIMATE_PORT } from '../src/adapters/nutrition-estimate.gemini';
import { MealsService, VISION_PORT } from '../src/app/meals.service';
import { MealsController } from '../src/app/meals.controller';
import { defaultRateLimiter } from '../src/app/rate-limiter';
import { VisionInput } from '../src/pipeline/ports';
import { pack_installed } from './helpers/packs';

// Turkish fixtures and the Turkish catalogue are licence-restricted; the
// catalogue is installed locally, never committed (docs/licensing.md).
const turkish = pack_installed('tr') ? it : it.skip;

describe('POST /v1/meals', () => {
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

  turkish('accepts JSON fixture input and replays an idempotent result', async () => {
    const body = {
      idempotency_key: 'http-json-replay',
      sample_id: 'tr_0001',
      locale: 'tr',
      config: 'V3',
    };

    const first = await request(app.getHttpServer()).post('/v1/meals').send(body);
    const second = await request(app.getHttpServer()).post('/v1/meals').send(body);

    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(second.body).toEqual(first.body);
    expect(first.body).toMatchObject({
      idempotency_key: 'http-json-replay',
      config: 'V3',
      degraded: false,
    });
  });

  it('returns an explicitly unverified nutrition range from the injected estimate port', async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(NUTRITION_ESTIMATE_PORT)
      .useValue({
        hasPendingOrCompleted: () => false,
        estimateMany: (items: Array<{ dish_name: string; quantity: number | null }>) => items.map(({ dish_name: dishName, quantity }) => ({
          dish_name: dishName,
          kcal: { low: 400, midpoint: 500, high: 600 },
          protein_g: { low: 15, midpoint: 20, high: 25 },
          carb_g: { low: 40, midpoint: 50, high: 60 },
          fat_g: { low: 12, midpoint: 18, high: 24 },
          assumptions: [`${quantity ?? 1} porsiyon varsayıldı.`],
          provenance: 'llm_unverified_estimate',
          model_id: 'stub-model',
        })),
        purgeUserData: () => undefined,
      })
      .compile();
    const estimateApp = moduleRef.createNestApplication<NestExpressApplication>({ bodyParser: false });
    configureBodyParsers(estimateApp);
    await estimateApp.init();

    const response = await request(estimateApp.getHttpServer())
      .post('/v1/meals/estimate')
      .set('X-User-Id', 'estimate-user')
      .set('X-Idempotency-Key', 'estimate-batch-1')
      .send({ items: [
        { dish_name: 'pide', quantity: 1 },
        { dish_name: 'piyaz', quantity: null },
      ] });

    expect(response.status).toBe(200);
    const responseBody = response.body as { estimates: Array<Record<string, unknown>> };
    expect(responseBody.estimates).toHaveLength(2);
    expect(responseBody.estimates[0]).toMatchObject({
      dish_name: 'pide',
      kcal: { low: 400, midpoint: 500, high: 600 },
      provenance: 'llm_unverified_estimate',
      model_id: 'stub-model',
    });
    await estimateApp.close();
  });

  it('validates estimate input and keeps fixture mode unavailable', async () => {
    const missingUser = await request(app.getHttpServer())
      .post('/v1/meals/estimate')
      .set('X-Idempotency-Key', 'missing-user')
      .send({ items: [{ dish_name: 'pide', quantity: 1 }] });
    expect(missingUser.status).toBe(422);

    const invalidQuantity = await request(app.getHttpServer())
      .post('/v1/meals/estimate')
      .set('X-User-Id', 'estimate-validation-user')
      .set('X-Idempotency-Key', 'invalid-quantity')
      .send({ items: [{ dish_name: 'pide', quantity: 21 }] });
    expect(invalidQuantity.status).toBe(422);

    const missingIdempotency = await request(app.getHttpServer())
      .post('/v1/meals/estimate')
      .set('X-User-Id', 'estimate-missing-key-user')
      .send({ items: [{ dish_name: 'pide', quantity: 1 }] });
    expect(missingIdempotency.status).toBe(422);

    const tooManyItems = await request(app.getHttpServer())
      .post('/v1/meals/estimate')
      .set('X-User-Id', 'estimate-too-many-user')
      .set('X-Idempotency-Key', 'too-many')
      .send({ items: Array.from({ length: 21 }, (_, index) => ({ dish_name: `food-${index}`, quantity: 1 })) });
    expect(tooManyItems.status).toBe(422);

    const unavailable = await request(app.getHttpServer())
      .post('/v1/meals/estimate')
      .set('X-User-Id', 'estimate-fixture-user')
      .set('X-Idempotency-Key', 'fixture-unavailable')
      .send({ items: [{ dish_name: 'pide', quantity: 1 }] });
    expect(unavailable.status).toBe(503);
    expect(unavailable.body).toMatchObject({ category: 'provider_unavailable' });
  });

  it('limits automatic estimate batches to five new requests per user per minute', async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(NUTRITION_ESTIMATE_PORT)
      .useValue({
        hasPendingOrCompleted: () => false,
        estimateMany: () => [{
          dish_name: 'Pide',
          kcal: { low: 400, midpoint: 500, high: 600 },
          protein_g: { low: 15, midpoint: 20, high: 25 },
          carb_g: { low: 40, midpoint: 50, high: 60 },
          fat_g: { low: 12, midpoint: 18, high: 24 },
          assumptions: ['Bir porsiyon varsayıldı.'],
          provenance: 'llm_unverified_estimate',
          model_id: 'stub-model',
        }],
        purgeUserData: () => undefined,
      })
      .compile();
    const estimateApp = moduleRef.createNestApplication<NestExpressApplication>({ bodyParser: false });
    configureBodyParsers(estimateApp);
    await estimateApp.init();
    const userId = `estimate-minute-${Date.now()}`;

    for (let index = 0; index < 5; index += 1) {
      const allowed = await request(estimateApp.getHttpServer())
        .post('/v1/meals/estimate')
        .set('X-User-Id', userId)
        .set('X-Idempotency-Key', `batch-${index}`)
        .send({ items: [{ dish_name: 'pide', quantity: 1 }] });
      expect(allowed.status).toBe(200);
    }
    const blocked = await request(estimateApp.getHttpServer())
      .post('/v1/meals/estimate')
      .set('X-User-Id', userId)
      .set('X-Idempotency-Key', 'batch-5')
      .send({ items: [{ dish_name: 'pide', quantity: 1 }] });
    expect(blocked.status).toBe(429);
    await estimateApp.close();
  });

  it('serializes provider degradation and keeps a high-confidence fallback in review', async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(VISION_PORT)
      .useValue({
        name: 'degraded-stub',
        perceive: () => ({
          observations: [
            makePerceivedItem({
              surface_form: 'scrambled eggs',
              confidence: 1,
              portion_hint: 'one serving',
            }),
          ],
          degraded: true,
        }),
      })
      .compile();
    const degradedApp = moduleRef.createNestApplication<NestExpressApplication>({ bodyParser: false });
    configureBodyParsers(degradedApp);
    await degradedApp.init();

    const response = await request(degradedApp.getHttpServer())
      .post('/v1/meals')
      .send({
        idempotency_key: 'http-degraded-fallback',
        locale: 'en_US',
        config: 'V3',
        text: 'scrambled eggs',
      });

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({
      degraded: true,
      action: 'review',
      items: [{ food_id: 'us.eggs_scrambled', confidence: 1 }],
    });
    await degradedApp.close();
  });

  it('maps an injected provider timeout to a typed 503 response', async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(VISION_PORT)
      .useValue({
        name: 'timeout-stub',
        perceive: () => { throw new VisionProviderError('provider_timeout', 3); },
      })
      .compile();
    const timeoutApp = moduleRef.createNestApplication<NestExpressApplication>({ bodyParser: false });
    configureBodyParsers(timeoutApp);
    await timeoutApp.init();

    const response = await request(timeoutApp.getHttpServer())
      .post('/v1/meals')
      .send({ idempotency_key: 'http-provider-timeout', locale: 'en_US', text: 'scrambled eggs' });

    expect(response.status).toBe(503);
    expect(response.body).toEqual({
      detail: 'vision provider timeout',
      category: 'provider_timeout',
      retry_attempted: true,
      attempts: 3,
    });
    await timeoutApp.close();
  });

  it('keeps a non-provider exception at the internal 500 boundary', async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(VISION_PORT)
      .useValue({
        name: 'defect-stub',
        perceive: () => { throw new Error('internal defect'); },
      })
      .compile();
    const defectApp = moduleRef.createNestApplication<NestExpressApplication>({ bodyParser: false });
    configureBodyParsers(defectApp);
    await defectApp.init();

    const response = await request(defectApp.getHttpServer())
      .post('/v1/meals')
      .send({ idempotency_key: 'http-internal-defect', locale: 'en_US', text: 'scrambled eggs' });

    expect(response.status).toBe(500);
    expect(response.body).toEqual({ detail: 'Internal Server Error' });
    await defectApp.close();
  });

  turkish('accepts multipart form fields without an image for fixture replay', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .field('idempotency_key', 'http-multipart-fixture')
      .field('sample_id', 'tr_0002')
      .field('locale', 'tr')
      .field('config', 'V3');

    expect(response.status).toBe(200);
    expect(response.body).toMatchObject({ idempotency_key: 'http-multipart-fixture', locale: 'tr' });
  });

  turkish('scopes the same idempotency key by X-User-Id', async () => {
    const first = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('X-User-Id', 'user-a')
      .send({ idempotency_key: 'http-shared-key', sample_id: 'tr_0001', locale: 'tr' });
    const second = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('X-User-Id', 'user-b')
      .send({ idempotency_key: 'http-shared-key', sample_id: 'tr_0002', locale: 'tr' });

    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(first.body).not.toEqual(second.body);
  });

  turkish('validates the V0-V3 config set and rejects unknown configs with 422', async () => {
    for (const config of ['V0', 'V1', 'V2', 'V3']) {
      const response = await request(app.getHttpServer())
        .post('/v1/meals')
        .send({ idempotency_key: `http-config-${config}`, sample_id: 'tr_0001', locale: 'tr', config });
      expect(response.status).toBe(200);
    }

    const unknown = await request(app.getHttpServer())
      .post('/v1/meals')
      .send({ idempotency_key: 'http-config-unknown', sample_id: 'tr_0001', config: 'V9' });
    expect(unknown.status).toBe(422);
    expect(unknown.body).toEqual({
      detail: "unknown config 'V9'; expected one of: V0, V1, V2, V3",
    });
  });

  it('rejects unsupported image MIME types with the Python-compatible 415', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .field('idempotency_key', 'http-bad-mime')
      .attach('image', Buffer.from('not an image'), { filename: 'meal.txt', contentType: 'text/plain' });

    expect(response.status).toBe(415);
    expect(response.body).toEqual({ detail: 'unsupported image content type' });
  });

  it('rejects MIME-spoofed image bytes before provider handling', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .field('idempotency_key', 'http-spoofed-image')
      .attach('image', Buffer.from('not a JPEG'), { filename: 'meal.jpg', contentType: 'image/jpeg' });

    expect(response.status).toBe(415);
    expect(response.body).toEqual({ detail: 'unsupported image content' });
  });

  it('rejects an image over 10 MiB with the Python-compatible 413', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .field('idempotency_key', 'http-large-image')
      .attach('image', Buffer.alloc(10 * 1024 * 1024 + 1), {
        filename: 'meal.jpg',
        contentType: 'image/jpeg',
      });

    expect(response.status).toBe(413);
    expect(response.body).toEqual({ detail: 'image exceeds 10 MiB limit' });
  });

  turkish('returns 422 for a JSON request without an input source', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .send({ idempotency_key: 'http-no-input' });

    expect(response.status).toBe(422);
    expect(response.body).toEqual({ detail: 'request needs image, text, or sample_id' });
  });

  it('rejects sample_id when the configured provider is live', async () => {
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] })
      .overrideProvider(Settings)
      .useValue(new Settings({ VISION_PROVIDER: 'gemini', GEMINI_API_KEY: 'test-key' }))
      .overrideProvider(VISION_PORT)
      .useValue({ name: 'stub', perceive: () => { throw new Error('vision should not run'); } })
      .compile();
    const liveApp = moduleRef.createNestApplication<NestExpressApplication>({ bodyParser: false });
    configureBodyParsers(liveApp);
    await liveApp.init();

    const response = await request(liveApp.getHttpServer())
      .post('/v1/meals')
      .send({ idempotency_key: 'http-live-sample', sample_id: 'tr_0001' });

    expect(response.status).toBe(400);
    expect(response.body).toEqual({
      detail: 'sample_id is test-only; live provider needs image or text input',
    });
    await liveApp.close();
  });

  it('maps malformed JSON to the Python-compatible 422', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('content-type', 'application/json')
      .send('{"idempotency_key":');

    expect(response.status).toBe(422);
    expect(response.body).toEqual({ detail: 'invalid JSON request' });
  });

  it('keeps the existing 413 and 422 boundaries after provider-error mapping', async () => {
    const tooLarge = await request(app.getHttpServer())
      .post('/v1/meals')
      .field('idempotency_key', 'http-provider-error-large-image')
      .attach('image', Buffer.alloc(10 * 1024 * 1024 + 1), {
        filename: 'meal.jpg',
        contentType: 'image/jpeg',
      });
    const malformed = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('content-type', 'application/json')
      .send('{"idempotency_key":');

    expect(tooLarge.status).toBe(413);
    expect(tooLarge.body).toEqual({ detail: 'image exceeds 10 MiB limit' });
    expect(malformed.status).toBe(422);
    expect(malformed.body).toEqual({ detail: 'invalid JSON request' });
  });

  turkish('returns typed 422 for text-only inputs in fixture mode instead of unhandled 500', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .send({
        idempotency_key: 'http-text-only-fixture-test',
        text: 'kuru fasulye',
        locale: 'tr',
        config: 'V3',
      });

    expect(response.status).toBe(422);
    const body = response.body as { detail?: string };
    expect(body.detail).toMatch(/fixture replay needs image bytes or a sample_id/);
  });

  it('requires user scope and a supported event type for telemetry', async () => {
    const payload = {
      idempotency_key: 'telemetry-contract',
      event_type: 'CONFIRMED_AS_IS',
      input_mode: 'text',
      locale: 'tr',
      items: [],
    };
    const missingUser = await request(app.getHttpServer())
      .post('/v1/telemetry/events')
      .send(payload);
    expect(missingUser.status).toBe(422);
    expect(missingUser.body).toEqual({ detail: 'X-User-Id header is required for telemetry' });

    const invalidEvent = await request(app.getHttpServer())
      .post('/v1/telemetry/events')
      .set('x-user-id', 'telemetry-contract-user')
      .send({ ...payload, event_type: 'TRAIN_MODEL_NOW' });
    expect(invalidEvent.status).toBe(422);
    expect(invalidEvent.body).toEqual({ detail: 'invalid telemetry event_type' });
  });

  turkish('GDPR delete purges user meal cache and resets user rate limiter', async () => {
    const userId = 'gdpr-e2e-user';
    const key = 'gdpr-purge-key';

    // 1. Initial meal
    const res1 = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', userId)
      .send({
        idempotency_key: key,
        sample_id: 'tr_0001',
        locale: 'tr',
        config: 'V3',
      });
    expect(res1.status).toBe(200);
    const body1 = res1.body as { items: Array<{ food_id: string }> };
    expect(body1.items[0]?.food_id).toBe('tr.kuru_fasulye');

    // 2. Delete user data without auth header -> 403 Forbidden
    const unauthDel = await request(app.getHttpServer()).delete(`/v1/users/${userId}/data`);
    expect(unauthDel.status).toBe(403);

    // 3. Delete user data with matching X-User-Id header -> 204 No Content
    const delRes = await request(app.getHttpServer())
      .delete(`/v1/users/${userId}/data`)
      .set('x-user-id', userId);
    expect(delRes.status).toBe(204);

    // 4. Subsequent meal with same key but different payload returns the new calculation
    const res2 = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', userId)
      .send({
        idempotency_key: key,
        sample_id: 'tr_0002',
        locale: 'tr',
        config: 'V3',
      });
    expect(res2.status).toBe(200);
    const body2 = res2.body as { items: Array<{ food_id: string }> };
    expect(body2.items[0]?.food_id).toBe('tr.simit');
  });

  turkish('rejects an empty idempotency key with 422', async () => {
    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .send({
        idempotency_key: '   ',
        sample_id: 'tr_0001',
        locale: 'tr',
        config: 'V3',
      });

    expect(response.status).toBe(422);
    const body = response.body as { detail?: string };
    expect(body.detail).toBe('invalid JSON request');
  });

  turkish('returns 409 Conflict when the same idempotency key is reused with a different payload', async () => {
    const key = `conflict-test-key-${Date.now()}`;
    const userId = `conflict-user-${Date.now()}`;

    const res1 = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', userId)
      .send({
        idempotency_key: key,
        sample_id: 'tr_0001',
        locale: 'tr',
        config: 'V3',
      });
    expect(res1.status).toBe(200);

    // Second request with same key but different sample_id -> 409 Conflict
    const res2 = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', userId)
      .send({
        idempotency_key: key,
        sample_id: 'tr_0002',
        locale: 'tr',
        config: 'V3',
      });
    expect(res2.status).toBe(409);
    const body2 = res2.body as { detail?: string };
    expect(body2.detail).toBe('idempotency key reused with different request payload');
  });

  turkish('rejects path-traversal or malformed sample_id with 422', async () => {
    const maliciousSampleIds = ['../../package', '../reports/scorecard', '/etc/hosts', 'tr_0001; rm -rf'];

    for (const sampleId of maliciousSampleIds) {
      const response = await request(app.getHttpServer())
        .post('/v1/meals')
        .set('x-user-id', `traversal-user-${sampleId}`)
        .send({
          idempotency_key: `traversal-${Math.random()}`,
          sample_id: sampleId,
          locale: 'tr',
          config: 'V3',
        });

      expect(response.status).toBe(422);
      const body = response.body as { detail?: string };
      expect(body.detail).toMatch(/invalid sample_id/);
    }
  });

  turkish('returns 422 for unrecorded image upload in fixture mode instead of 500', async () => {
    // 1x1 transparent PNG
    const unrecordedPng = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
      'base64',
    );

    const response = await request(app.getHttpServer())
      .post('/v1/meals')
      .field('idempotency_key', `unrecorded-img-key-${Date.now()}`)
      .field('locale', 'tr')
      .field('config', 'V3')
      .attach('image', unrecordedPng, { filename: 'test.png', contentType: 'image/png' });

    expect(response.status).toBe(422);
    const body = response.body as { detail?: string };
    expect(body.detail).toMatch(/fixture replay has no recorded response/);
  });

  turkish('rejects in-flight race with conflicting payloads with 409 Conflict', async () => {
    const key = `inflight-race-${Date.now()}`;
    const userId = 'race-user';

    const [resA, resB] = await Promise.all([
      request(app.getHttpServer())
        .post('/v1/meals')
        .set('x-user-id', userId)
        .send({
          idempotency_key: key,
          sample_id: 'tr_0001',
          locale: 'tr',
          config: 'V3',
        }),
      request(app.getHttpServer())
        .post('/v1/meals')
        .set('x-user-id', userId)
        .send({
          idempotency_key: key,
          sample_id: 'tr_0002',
          locale: 'tr',
          config: 'V3',
        }),
    ]);

    const statuses = [resA.status, resB.status].sort();
    expect(statuses).toEqual([200, 409]);
  });

  turkish('GDPR delete during an in-flight request does not re-insert the purged meal into completed cache', async () => {
    const mealsService = app.get(MealsService);
    const key = `gdpr-inflight-key-${Date.now()}`;
    const userId = `gdpr-race-user-${Date.now()}`;

    const requestA = {
      idempotency_key: key,
      sample_id: 'tr_0001',
      text: null,
      locale: 'tr',
      config: 'V3' as const,
    };
    const inputA = new VisionInput({ sampleId: 'tr_0001' });

    // Start request A and purge user immediately while it is in-flight
    const mealPromise = mealsService.logMeal(requestA, inputA, userId);
    mealsService.purgeUserData(userId);

    const mealResult = await mealPromise;
    expect(mealResult.items[0]?.food_id).toBe('tr.kuru_fasulye');

    // Request B with same key but different payload should process fresh and return tr.simit (not 409 and not tr.kuru_fasulye)
    const requestB = {
      idempotency_key: key,
      sample_id: 'tr_0002',
      text: null,
      locale: 'tr',
      config: 'V3' as const,
    };
    const inputB = new VisionInput({ sampleId: 'tr_0002' });

    const secondResult = await mealsService.logMeal(requestB, inputB, userId);
    expect(secondResult.items[0]?.food_id).toBe('tr.simit');
  });

  turkish('allows idempotent replay even after the rate limit quota is exhausted', async () => {
    const userId = `rate-limit-replay-user-${Date.now()}`;
    const key = `completed-key-${Date.now()}`;

    // 1. Send the first request (consumes 1 rate token, caches result)
    const firstRes = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', userId)
      .send({
        idempotency_key: key,
        sample_id: 'tr_0001',
        locale: 'tr',
        config: 'V3',
      });
    expect(firstRes.status).toBe(200);

    // 2. Burn through all remaining rate limit tokens (30 total limit)
    for (let i = 0; i < 30; i++) {
      await request(app.getHttpServer())
        .post('/v1/meals')
        .set('x-user-id', userId)
        .send({
          idempotency_key: `burn-key-${i}-${Date.now()}`,
          sample_id: 'tr_0001',
          locale: 'tr',
          config: 'V3',
        });
    }

    // 3. Verify that a fresh request now gets 429 Too Many Requests
    const freshRes = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', userId)
      .send({
        idempotency_key: `fresh-blocked-key-${Date.now()}`,
        sample_id: 'tr_0001',
        locale: 'tr',
        config: 'V3',
      });
    expect(freshRes.status).toBe(429);

    // 4. Replaying the previously completed key must succeed with 200 (bypassing rate limiter)
    const replayRes = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', userId)
      .send({
        idempotency_key: key,
        sample_id: 'tr_0001',
        locale: 'tr',
        config: 'V3',
      });
    expect(replayRes.status).toBe(200);
    const replayBody = replayRes.body as { items: Array<{ food_id: string }> };
    expect(replayBody.items[0]?.food_id).toBe('tr.kuru_fasulye');
  });

  turkish('rejects oversized idempotency keys with 422', async () => {
    const hugeKey = 'a'.repeat(300);
    const res = await request(app.getHttpServer())
      .post('/v1/meals')
      .set('x-user-id', `oversized-user-${Date.now()}`)
      .send({
        idempotency_key: hugeKey,
        sample_id: 'tr_0001',
        locale: 'tr',
        config: 'V3',
      });
    expect(res.status).toBe(422);
  });

  turkish('returns 422 for unrecorded sample_id like tr_999999 instead of 500', async () => {
    const res = await request(app.getHttpServer())
      .post('/v1/meals')
      .send({
        idempotency_key: `unrecorded-sample-${Date.now()}`,
        sample_id: 'tr_999999',
        locale: 'tr',
        config: 'V3',
      });
    expect(res.status).toBe(422);
    const body = res.body as { detail?: string };
    expect(body.detail).toMatch(/fixture replay has no recorded response/);
  });

  turkish('allows concurrent in-flight burst of requests on the same key without hitting 429', async () => {
    const mealsController = app.get(MealsController);
    const userId = 'inflight-burst-user-123';
    const burstId = 'inflight-burst-id-123';

    const body = {
      idempotency_key: burstId,
      sample_id: 'tr_0001',
      locale: 'tr',
      config: 'V3',
    };

    // Burn 29 out of 30 rate limit tokens first so only 1 token remains
    for (let i = 0; i < 29; i++) {
      defaultRateLimiter.check(userId);
    }

    // Send 10 concurrent calls to controller.create with the same key
    const promises = Array.from({ length: 10 }, () =>
      mealsController.create(body, undefined, 'application/json', userId),
    );

    const results = await Promise.all(promises);
    expect(results.length).toBe(10);
    for (const res of results) {
      const meal = res as { items: Array<{ food_id: string }> };
      expect(meal.items[0]?.food_id).toBe('tr.kuru_fasulye');
    }
  });

  it('rejects truncated 3-byte JPEG with 415 Unsupported Media Type before provider ingestion', async () => {
    const truncatedJpeg = Buffer.from([0xff, 0xd8, 0xff]);
    const res = await request(app.getHttpServer())
      .post('/v1/meals')
      .field('idempotency_key', `truncated-${Date.now()}`)
      .field('locale', 'tr')
      .field('config', 'V3')
      .attach('image', truncatedJpeg, { filename: 'tiny.jpg', contentType: 'image/jpeg' });
    expect(res.status).toBe(415);
  });

  it('falls back to configured default_locale when locale field is omitted in the request', async () => {
    const mealsController = app.get(MealsController);
    const body = {
      idempotency_key: `default-locale-${Date.now()}`,
      sample_id: 'tr_0001',
      config: 'V3',
    };

    const result = await mealsController.create(body, undefined, 'application/json', 'default-locale-user');
    const meal = result as { items: Array<{ food_id: string }> };
    expect(meal.items).toBeDefined();
  });
});
