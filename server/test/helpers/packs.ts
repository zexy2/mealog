import { existsSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

/**
 * Pack root used by the test suite.
 *
 * Restricted catalogues are never committed, so tests read packs from a
 * temporary fixture that `vitest.config.ts` assembles from the repository plus
 * any locally installed Turkish catalogue. Falling back to the repository
 * keeps a single `vitest` invocation working when the fixture is not set.
 */
export const TEST_PACK_ROOT = process.env.MEALOG_TEST_PACK_ROOT
  ?? resolve(__dirname, '../../locale_packs');

/** True when a pack ships its catalogue in the given root. */
export function pack_installed(locale: string, root: string = TEST_PACK_ROOT): boolean {
  const directory = join(root, locale);
  return existsSync(join(directory, 'foods.jsonl'));
}

/** Locales that ship, i.e. those a plain checkout can load. */
export function shipped_locales(root: string = TEST_PACK_ROOT): string[] {
  return readdirSync(root)
    .filter((name) => existsSync(join(root, name, 'pack.yaml')))
    .filter((name) => pack_installed(name, root))
    .sort();
}
