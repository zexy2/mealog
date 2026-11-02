import { Module } from '@nestjs/common';
import { APP_FILTER, APP_INTERCEPTOR } from '@nestjs/core';

import { FixtureVision } from '../adapters/vision.fixture';
import { GeminiVision } from '../adapters/vision.gemini';
import {
  DisabledNutritionEstimator,
  GeminiNutritionEstimator,
  NUTRITION_ESTIMATE_PORT,
} from '../adapters/nutrition-estimate.gemini';
import { settings, Settings } from '../config';
import { configure as configureLogging } from '../obs';
import type { VisionPort } from '../pipeline/ports';

import { HealthController, MetricsController } from './health.controller';
import { HttpExceptionFilter } from './http-exception.filter';
import { MealsController } from './meals.controller';
import { FoodsService } from './foods.service';
import { MealsService, VISION_PORT } from './meals.service';
import { ObservabilityInterceptor } from './observability.interceptor';

function makeVision(runtimeSettings: Settings): VisionPort {
  if (runtimeSettings.vision_provider === 'fixture') {
    return new FixtureVision();
  }
  if (runtimeSettings.vision_provider === 'gemini') {
    return new GeminiVision({ apiKey: runtimeSettings.gemini_api_key ?? '' });
  }
  throw new Error(`unknown vision provider: ${runtimeSettings.vision_provider}`);
}

// LOG_LEVEL is read once, here, so the level is fixed before the first request
// rather than re-derived per log line.
configureLogging(settings.log_level);

/**
 * Composition root for the edge.
 *
 * Under the port epic's proposed D12, NestJS lives at the edge only:
 * controllers and providers. Pipeline modules are wired in as plain functions
 * and pure classes in later waves, so that the eval harness can import the same
 * modules without booting Nest.
 */
@Module({
  controllers: [HealthController, MetricsController, MealsController],
  providers: [
    { provide: Settings, useValue: settings },
    // Observability is global at the edge, not sprinkled per controller: a
    // request that is not logged is a request that cannot be explained.
    { provide: APP_INTERCEPTOR, useClass: ObservabilityInterceptor },
    {
      provide: VISION_PORT,
      useFactory: (runtimeSettings: Settings) => makeVision(runtimeSettings),
      inject: [Settings],
    },
    {
      provide: NUTRITION_ESTIMATE_PORT,
      useFactory: (runtimeSettings: Settings) => runtimeSettings.vision_provider === 'gemini'
        ? new GeminiNutritionEstimator({ apiKey: runtimeSettings.gemini_api_key ?? '' })
        : new DisabledNutritionEstimator(),
      inject: [Settings],
    },
    MealsService,
    FoodsService,
    { provide: APP_FILTER, useClass: HttpExceptionFilter },
  ],
})
export class AppModule {}
