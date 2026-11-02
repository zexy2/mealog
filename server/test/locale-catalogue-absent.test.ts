import { expect, it } from 'vitest';

import { load, PackUnavailableError } from '../src/locales/loader';
import { pack_installed, shipped_locales, TEST_PACK_ROOT } from './helpers/packs';

/**
 * Pins what a clean clone can load. The Turkish catalogue is
 * `restricted-noncommercial` and is installed locally instead of committed;
 * these assertions hold whether or not that install happened.
 */
it('loads every pack whose catalogue ships, and only those', () => {
  expect(shipped_locales()).toEqual(
    pack_installed('tr') ? ['en_US', 'ja_JP', 'tr'] : ['en_US', 'ja_JP'],
  );
  for (const locale of shipped_locales()) {
    expect(Object.keys(load(locale, TEST_PACK_ROOT).foods).length).toBeGreaterThan(0);
  }
});

it('reports a restricted catalogue that was not installed as unavailable', () => {
  if (pack_installed('tr')) {
    // Installed locally: the pack is complete and behaves like any other.
    expect(Object.keys(load('tr', TEST_PACK_ROOT).foods).length).toBeGreaterThan(0);
    return;
  }
  let caught: unknown;
  try {
    load('tr', TEST_PACK_ROOT);
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(PackUnavailableError);
  expect((caught as PackUnavailableError).locale).toBe('tr');
  expect((caught as PackUnavailableError).message).toContain('docs/licensing.md');
  expect((caught as PackUnavailableError).message).toContain('en_US, ja_JP');
});
