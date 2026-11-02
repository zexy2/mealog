import { Inject, Injectable, HttpException, HttpStatus } from '@nestjs/common';

import { FixtureVision } from '../adapters/vision.fixture';
import { settings, Settings } from '../config';
import { event, stageAsync } from '../obs';
import { CONFIGS, run, type Config } from '../pipeline/runner';
import { VisionInput, type VisionPort } from '../pipeline/ports';
import type { MealLog } from '../domain/models';
import { applyCorrections, type CorrectionRequest } from '../pipeline/correction';
import { PackUnavailableError } from '../locales/loader';

export const VISION_PORT = Symbol('VISION_PORT');
export const DEMO_USER_ID = 'demo-user';

export interface MealRequest {
  readonly idempotency_key: string;
  readonly sample_id: string | null;
  readonly locale: string;
  readonly text: string | null;
  readonly config: string;
}

function error(status: HttpStatus, detail: string): never {
  throw new HttpException({ detail }, status);
}

interface CachedEntry {
  readonly result: MealLog;
  readonly fingerprint: string;
}

interface InFlightEntry {
  readonly promise: Promise<MealLog>;
  readonly fingerprint: string;
}

function fingerprintRequest(request: MealRequest, input: VisionInput): string {
  return [
    request.locale,
    request.config,
    request.sample_id ?? '',
    request.text ?? '',
    input.contentHash,
  ].join('\u0001');
}

/** Edge provider that owns request-level idempotency, not pipeline state. */
@Injectable()
export class MealsService {
  private static readonly MAX_CACHE_SIZE = 5000;
  private readonly completed = new Map<string, CachedEntry>();
  private readonly inFlight = new Map<string, InFlightEntry>();
  private readonly userPurgeGenerations = new Map<string, number>();

  constructor(
    @Inject(VISION_PORT) private readonly vision: VisionPort,
    @Inject(Settings) private readonly runtimeSettings: Settings = settings,
  ) {}

  hasPendingOrCompleted(userId: string | undefined, idempotencyKey: string): boolean {
    const normalizedUserId = userId?.trim() || DEMO_USER_ID;
    const cacheKey = `${normalizedUserId}\u0000${idempotencyKey}`;
    return this.completed.has(cacheKey) || this.inFlight.has(cacheKey);
  }

  async logMeal(
    request: MealRequest,
    input: VisionInput,
    userId: string | undefined,
  ): Promise<MealLog> {
    const config = CONFIGS[request.config];
    if (!config) {
      error(
        HttpStatus.UNPROCESSABLE_ENTITY,
        `unknown config '${request.config}'; expected one of: ${Object.keys(CONFIGS).sort().join(', ')}`,
      );
    }

    const normalizedUserId = userId?.trim() || DEMO_USER_ID;
    const cacheKey = `${normalizedUserId}\u0000${request.idempotency_key}`;
    const currentFingerprint = fingerprintRequest(request, input);
    const cached = this.completed.get(cacheKey);
    if (cached) {
      if (cached.fingerprint !== currentFingerprint) {
        error(
          HttpStatus.CONFLICT,
          'idempotency key reused with different request payload',
        );
      }
      // True LRU: delete and re-set so the accessed entry moves to the end of insertion order
      this.completed.delete(cacheKey);
      this.completed.set(cacheKey, cached);
      // Replays are logged. A duplicate that silently returns the first answer
      // looks like a fresh success in metrics unless it is named.
      event('idempotent_replay', { config: request.config, source: 'completed' });
      return cached.result;
    }

    const pending = this.inFlight.get(cacheKey);
    if (pending) {
      if (pending.fingerprint !== currentFingerprint) {
        error(
          HttpStatus.CONFLICT,
          'idempotency key reused with different request payload',
        );
      }
      event('idempotent_replay', { config: request.config, source: 'in_flight' });
      return pending.promise;
    }

    if (this.runtimeSettings.vision_provider !== 'fixture' && input.sampleId) {
      error(
        HttpStatus.BAD_REQUEST,
        'sample_id is test-only; live provider needs image or text input',
      );
    }

    if (this.vision instanceof FixtureVision && !input.sampleId && input.imageBytes === null) {
      error(
        HttpStatus.UNPROCESSABLE_ENTITY,
        'fixture replay needs image bytes or a sample_id; for free-text logging configure VISION_PROVIDER=gemini',
      );
    }

    const generation = this.userPurgeGenerations.get(normalizedUserId) ?? 0;
    const result = this.runOnce(cacheKey, request, input, config, normalizedUserId, generation);
    this.inFlight.set(cacheKey, { promise: result, fingerprint: currentFingerprint });
    return result;
  }

  correctMeal(request: CorrectionRequest): MealLog {
    try {
      return applyCorrections(request);
    } catch (caught) {
      if (caught instanceof Error) {
        error(HttpStatus.UNPROCESSABLE_ENTITY, caught.message);
      }
      error(HttpStatus.UNPROCESSABLE_ENTITY, 'invalid correction request');
    }
  }

  /**
   * Purges all completed and in-flight meal records associated with a specific user.
   */
  purgeUserData(userId: string): void {
    const normalizedUserId = userId?.trim() || DEMO_USER_ID;
    const nextGen = (this.userPurgeGenerations.get(normalizedUserId) ?? 0) + 1;
    this.userPurgeGenerations.set(normalizedUserId, nextGen);
    const prefix = `${normalizedUserId}\u0000`;
    for (const key of this.completed.keys()) {
      if (key.startsWith(prefix)) {
        this.completed.delete(key);
      }
    }
    for (const key of this.inFlight.keys()) {
      if (key.startsWith(prefix)) {
        this.inFlight.delete(key);
      }
    }
  }

  private async runOnce(
    cacheKey: string,
    request: MealRequest,
    input: VisionInput,
    config: Config,
    normalizedUserId: string,
    generation: number,
  ): Promise<MealLog> {
    try {
      // The identity of what produced the answer travels with the timing:
      // provider, config, locale, and input mode. Without those, a latency or
      // accuracy change cannot be attributed to a cause.
      const result = await stageAsync(
        'pipeline',
        () => run(this.vision, input, request.locale, config, request.idempotency_key),
        {
          config: request.config,
          provider: this.runtimeSettings.vision_provider,
          locale: request.locale,
          input_mode: this.inputModeOf(input),
        },
      );
      const currentGen = this.userPurgeGenerations.get(normalizedUserId) ?? 0;
      if (generation === currentGen) {
        if (this.completed.size >= MealsService.MAX_CACHE_SIZE) {
          const oldestEntry = this.completed.keys().next().value;
          if (oldestEntry) {
            this.completed.delete(oldestEntry);
          }
        }
        this.completed.set(cacheKey, {
          result,
          fingerprint: fingerprintRequest(request, input),
        });
      }
      return result;
    } catch (caught) {
      if (caught instanceof PackUnavailableError) {
        error(
          HttpStatus.SERVICE_UNAVAILABLE,
          `locale '${request.locale}' is defined but its licence-restricted catalogue is not installed in this deployment`,
        );
      }
      if (caught instanceof Error && /no locale pack at|unknown locale/i.test(caught.message)) {
        error(HttpStatus.UNPROCESSABLE_ENTITY, `unsupported or unknown locale '${request.locale}'`);
      }
      if (caught instanceof Error && /no recorded response for/i.test(caught.message)) {
        error(
          HttpStatus.UNPROCESSABLE_ENTITY,
          `fixture replay has no recorded response for '${request.sample_id ?? input.contentHash}'; for live photo perception configure VISION_PROVIDER=gemini`,
        );
      }
      throw caught;
    } finally {
      this.inFlight.delete(cacheKey);
    }

  }

  /**
   * Which path produced the meal. Photo and text are different products with
   * different failure modes — issue #218 is a photo-path defect that the text
   * path does not have — so the mode has to be on the record.
   */
  private inputModeOf(input: VisionInput): string {
    if (input.imageBytes) return 'image';
    if (input.text) return 'text';
    return 'sample_id';
  }
}
