import { cpSync, mkdirSync, mkdtempSync, readFileSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  CommercialUse,
  LicenseTerm,
  PackUnavailableError,
  RestrictedPackError,
  available,
  load,
  loadable,
  parse_license,
} from '../src/locales/loader';
import { TEST_PACK_ROOT, pack_installed } from './helpers/packs';

const PACK_ROOT = TEST_PACK_ROOT;
/** The Turkish catalogue is installed locally; it is never committed. */
const turkish = pack_installed('tr') ? it : it.skip;

describe('locale loader', () => {
  it('defines every pack, including the one whose catalogue is installed separately', () => {
    expect(available(PACK_ROOT)).toEqual(['en_US', 'ja_JP', 'tr']);
    expect(loadable(PACK_ROOT)).toEqual(
      available(PACK_ROOT).filter((locale) => pack_installed(locale)),
    );
  });

  it('loads every installed pack and keeps aliases inside the catalogue', () => {
    for (const locale of loadable(PACK_ROOT)) {
      const pack = load(locale, PACK_ROOT);
      expect(Object.keys(pack.foods).length).toBeGreaterThan(0);
      expect(pack.license).toBeTruthy();
      for (const foodId of Object.keys(pack.aliases)) {
        expect(pack.foods).toHaveProperty(foodId);
      }
    }
  });

  turkish('exposes a user-facing Turkish name for the whole-egg source record', () => {
    const egg = load('tr', PACK_ROOT).foods['tr.yumurta_tavuk'];

    expect(egg.name).toBe('Tavuk yumurtası');
    expect(egg.source).toBe('TURKOMP food code 02.01.0007');
    expect(egg.per_100g.kcal).toBe(140);
  });

  it('maps licence vocabulary and fails closed for unknown values', () => {
    expect(parse_license('public-domain')).toBe(LicenseTerm.PUBLIC_DOMAIN);
    expect(parse_license('RESTRICTED - non-commercial')).toBe(LicenseTerm.UNVERIFIED);
    expect(parse_license(undefined)).toBe(LicenseTerm.UNVERIFIED);
    expect(load('ja_JP', PACK_ROOT).commercial_use).toBe(CommercialUse.UNKNOWN);
  });

  turkish('marks the restricted pack as commercially prohibited', () => {
    expect(load('tr', PACK_ROOT).commercial_use).toBe(CommercialUse.PROHIBITED);
  });

  it('refuses restricted and unverified packs in commercial mode', () => {
    expect(() => load('ja_JP', PACK_ROOT, { commercial_mode: true })).toThrow(RestrictedPackError);
    expect(() => load('en_US', PACK_ROOT, { commercial_mode: true })).not.toThrow();
  });

  turkish('refuses the restricted pack in commercial mode', () => {
    expect(() => load('tr', PACK_ROOT, { commercial_mode: true })).toThrow(RestrictedPackError);
  });

  it('does not let a development cache warm bypass the licence gate', () => {
    const warm = load('ja_JP', PACK_ROOT, { commercial_mode: false });
    expect(warm.foods).not.toEqual({});
    expect(() => load('ja_JP', PACK_ROOT, { commercial_mode: true })).toThrow(
      'MEALOG_COMMERCIAL_MODE',
    );
  });

  it('fails with an instruction, not a crash, when a restricted catalogue is absent', () => {
    const root = makeMetadataOnlyRoot('pack-unavailable');
    expect(() => load('tr', root)).toThrow(PackUnavailableError);
    expect(() => load('tr', root)).toThrow(/docs\/licensing\.md/);
    // The pack is still advertised: it exists, its licence is known, and the
    // deployment simply does not carry its data.
    expect(available(root)).toContain('tr');
    expect(loadable(root)).not.toContain('tr');
  });

  it('treats a pack without a licence as unverified and refuses it commercially', () => {
    const root = makeFixtureRoot('license-missing');
    const packPath = join(root, 'xx_TEST', 'pack.yaml');
    writeFileSync(packPath, 'locale: xx_TEST\ncuisine_bucket: other_mixed\nnutrition_source: hand-typed\n');
    writeFileSync(join(root, 'xx_TEST', 'text_rules.yaml'), '{}\n');

    expect(load('xx_TEST', root).license).toBe(LicenseTerm.UNVERIFIED);
    expect(() => load('xx_TEST', root, { commercial_mode: true })).toThrow(RestrictedPackError);
  });

  it('rebuilds cache when pack content changes, not when mtime changes', () => {
    const root = makeFixtureRoot('content-cache');
    const first = load('xx_TEST', root);
    const foodsPath = join(root, 'xx_TEST', 'foods.jsonl');
    const oldTime = new Date('2020-01-01T00:00:00Z');
    utimesSync(foodsPath, oldTime, oldTime);
    const same = load('xx_TEST', root);
    expect(same).toBe(first);

    const foods = readFileSync(foodsPath, 'utf8').replace('Test food', 'Changed food');
    writeFileSync(foodsPath, foods);

    const rebuilt = load('xx_TEST', root);
    expect(rebuilt).not.toBe(first);
    expect(rebuilt.foods['xx.test'].name).toBe('Changed food');
  });
});

function makeMetadataOnlyRoot(label: string): string {
  const root = mkdtempSync(join(tmpdir(), `mealog-${label}-`));
  const directory = join(root, 'tr');
  mkdirSync(directory);
  cpSync(join(PACK_ROOT, 'tr', 'pack.yaml'), join(directory, 'pack.yaml'));
  writeFileSync(join(directory, 'text_rules.yaml'), '{}\n');
  return root;
}

function makeFixtureRoot(label: string): string {
  const root = mkdtempSync(join(tmpdir(), `mealog-${label}-`));
  cpSync(join(PACK_ROOT, 'en_US'), join(root, 'xx_TEST'), { recursive: true });
  const packPath = join(root, 'xx_TEST', 'pack.yaml');
  writeFileSync(
    packPath,
    readFileSync(packPath, 'utf8').replaceAll('en_US', 'xx_TEST').replace('western', 'other_mixed'),
  );
  const foodsPath = join(root, 'xx_TEST', 'foods.jsonl');
  writeFileSync(
    foodsPath,
    readFileSync(foodsPath, 'utf8')
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(0, 1)
      .map((line) => line
        .replace(/"food_id"\s*:\s*"[^"]+"/, '"food_id":"xx.test"')
        .replace(/"name"\s*:\s*"[^"]+"/, '"name":"Test food"'))
      .join('\n') + '\n',
  );
  return root;
}
