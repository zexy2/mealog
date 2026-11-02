/**
 * Drives the real application over HTTP to check the observability wiring.
 *
 * The unit tests in `obs.test.ts` prove the primitives work; these prove they
 * are actually connected — that the interceptor is registered globally, that
 * the id reaches the client, and that `/metrics` reports traffic that really
 * happened. A green unit suite with an unregistered interceptor is exactly the
 * failure this file exists to catch.
 */

import 'reflect-metadata';

import { Test } from '@nestjs/testing';
import type { NestExpressApplication } from '@nestjs/platform-express';
import request from 'supertest';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { AppModule } from '../src/app/app.module';
import { configureBodyParsers } from '../src/main';
import { metrics, type MetricsSnapshot } from '../src/obs';
import { pack_installed } from './helpers/packs';

// Turkish fixtures need the locally installed, non-committed catalogue.
const turkish = pack_installed('tr') ? it : it.skip;

describe('observability at the edge', () => {
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

  beforeEach(() => {
    metrics.reset();
  });

  const logMeal = (body: Record<string, unknown>) =>
    request(app.getHttpServer()).post('/v1/meals').send(body);

  const snapshot = async (): Promise<MetricsSnapshot> => {
    const response = await request(app.getHttpServer()).get('/metrics');
    expect(response.status).toBe(200);
    return response.body as MetricsSnapshot;
  };

  it('returns a request id the caller can quote in a support ticket', async () => {
    const response = await request(app.getHttpServer()).get('/health');

    expect(response.headers['x-request-id']).toMatch(/^[0-9a-f]{12}$/);
  });

  it('gives different requests different ids', async () => {
    const first = await request(app.getHttpServer()).get('/health');
    const second = await request(app.getHttpServer()).get('/health');

    expect(first.headers['x-request-id']).not.toBe(second.headers['x-request-id']);
  });

  it('honours a client-supplied id so a mobile trace survives into server logs', async () => {
    const response = await request(app.getHttpServer())
      .get('/health')
      .set('X-Request-Id', 'client-abc-123');

    expect(response.headers['x-request-id']).toBe('client-abc-123');
  });

  it('rejects an absurdly long client id instead of logging it verbatim', async () => {
    const response = await request(app.getHttpServer())
      .get('/health')
      .set('X-Request-Id', 'x'.repeat(200));

    expect(response.headers['x-request-id']).toMatch(/^[0-9a-f]{12}$/);
  });

  turkish('counts a successful meal under its route and status', async () => {
    await logMeal({
      idempotency_key: 'obs-success',
      sample_id: 'tr_0001',
      locale: 'tr',
      config: 'V3',
    });

    expect((await snapshot()).requests_total['POST /v1/meals 200']).toBe(1);
  });

  turkish('counts a rejected request rather than dropping it from the record', async () => {
    await logMeal({
      idempotency_key: 'obs-bad-config',
      sample_id: 'tr_0001',
      locale: 'tr',
      config: 'V99',
    });

    const requests = (await snapshot()).requests_total;
    expect(requests['POST /v1/meals 422']).toBe(1);
    expect(requests['POST /v1/meals 200']).toBeUndefined();
  });

  turkish('records the gate decision, not just the status code', async () => {
    await logMeal({
      idempotency_key: 'obs-decision',
      sample_id: 'tr_0001',
      locale: 'tr',
      config: 'V3',
    });

    const outcomes = (await snapshot()).outcomes_total;
    expect(Object.keys(outcomes)).toHaveLength(1);
    expect(Object.values(outcomes)[0]).toBe(1);
  });

  turkish('times the pipeline stage separately from the request', async () => {
    await logMeal({
      idempotency_key: 'obs-stages',
      sample_id: 'tr_0001',
      locale: 'tr',
      config: 'V3',
    });

    const current = await snapshot();
    expect(current.stage_latency.pipeline.count).toBe(1);
    expect(current.request_latency.count).toBeGreaterThanOrEqual(1);
  });

  it('reports an empty but well-formed snapshot before any traffic', async () => {
    const current = await snapshot();

    expect(current.outcomes_total).toEqual({});
    expect(current.request_latency.count).toBe(0);
    expect(current.request_latency.p50_ms).toBeNull();
    expect(typeof current.uptime_s).toBe('number');
  });

  it('exposes only aggregates — no meal contents, no user ids', async () => {
    await logMeal({
      idempotency_key: 'obs-privacy',
      locale: 'en_US',
      config: 'V3',
      text: 'scrambled eggs and toast',
    });

    const serialized = JSON.stringify(await snapshot());
    expect(serialized).not.toContain('scrambled eggs');
    expect(serialized).not.toContain('obs-privacy');
    expect(serialized).not.toContain('demo-user');
  });
});
