import { cpSync, existsSync, mkdtempSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { defineConfig } from 'vitest/config';

const REPO_PACKS = resolve(__dirname, '../locale_packs');

/**
 * Test packs live outside the repository so that no restricted catalogue is
 * ever committed, while the suite still exercises the Turkish pack fully.
 *
 * The Turkish catalogue is installed with `scripts/install_restricted_pack.py`
 * (see docs/licensing.md). When it is absent, this fixture copies the packs
 * that do ship and leaves `tr` metadata-only — exactly what CI sees.
 */
function fixturePackRoot(): string {
  const fixture = mkdtempSync(join(tmpdir(), 'mealog-test-packs-'));
  for (const name of readdirSync(REPO_PACKS)) {
    cpSync(join(REPO_PACKS, name), join(fixture, name), { recursive: true });
  }
  const installed = process.env.MEALOG_TR_PACK_DIR;
  if (installed && existsSync(installed)) {
    for (const file of ['foods.jsonl', 'aliases.jsonl', 'units.jsonl']) {
      const source = join(installed, file);
      if (existsSync(source)) cpSync(source, join(fixture, 'tr', file));
    }
  }
  return fixture;
}

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.ts'],
    // server/tests/ is the Python suite and server/src/mealog/ is the Python
    // backend; both stay untouched until the port epic's parity gate passes.
    exclude: ['node_modules/**', 'dist/**', 'tests/**', 'src/mealog/**'],
    env: {
      MEALOG_TEST_PACK_ROOT: fixturePackRoot(),
    },
  },
  esbuild: {
    // NestJS relies on TypeScript's legacy decorator semantics. esbuild reads
    // experimentalDecorators from tsconfig.json; pinning the target keeps the
    // transform consistent with the tsc build.
    target: 'es2022',
  },
});
