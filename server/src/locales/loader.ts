import { createHash } from 'node:crypto';
import {
  existsSync,
  readFileSync,
  readdirSync,
  statSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';

import {
  type CanonicalFood,
  makeNutrients,
  validateCanonicalFood,
} from '../domain/models';
import { settings } from '../config';

/** Repository root's data boundary. Locale names never appear in code. */
function find_pack_root(start: string = dirname(__filename)): string {
  let current = resolve(start);
  for (let depth = 0; depth < 10; depth += 1) {
    const candidate = join(current, 'locale_packs');
    if (existsSync(candidate)) return candidate;
    const parent = dirname(current);
    if (parent === current) break;
    current = parent;
  }
  // Preserve a useful path in the eventual error if the repository is
  // incomplete rather than silently selecting another directory.
  return resolve(start, '../../../locale_packs');
}

export const PACK_ROOT = find_pack_root();
export const COMMERCIAL_MODE_ENV = 'MEALOG_COMMERCIAL_MODE';

export enum LicenseTerm {
  PUBLIC_DOMAIN = 'public-domain',
  PERMISSIVE = 'permissive',
  RESTRICTED_NONCOMMERCIAL = 'restricted-noncommercial',
  UNVERIFIED = 'unverified',
}

export enum CommercialUse {
  ALLOWED = 'allowed',
  PROHIBITED = 'prohibited',
  UNKNOWN = 'unknown',
}

export const _COMMERCIAL_USE: Readonly<Record<LicenseTerm, CommercialUse>> = {
  [LicenseTerm.PUBLIC_DOMAIN]: CommercialUse.ALLOWED,
  [LicenseTerm.PERMISSIVE]: CommercialUse.ALLOWED,
  [LicenseTerm.RESTRICTED_NONCOMMERCIAL]: CommercialUse.PROHIBITED,
  [LicenseTerm.UNVERIFIED]: CommercialUse.UNKNOWN,
};

export class RestrictedPackError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RestrictedPackError';
  }
}

export function parse_license(value: unknown): LicenseTerm {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return (Object.values(LicenseTerm) as string[]).includes(normalized)
    ? normalized as LicenseTerm
    : LicenseTerm.UNVERIFIED;
}

type YamlObject = Record<string, unknown>;

interface YamlLine {
  indent: number;
  raw: string;
  text: string;
}

/**
 * Parse the deliberately small YAML vocabulary used by locale packs.
 *
 * Pack metadata contains scalar fields and folded/literal notes. Text rules
 * additionally contain one nested string map (`char_map`). Keeping this parser
 * local avoids an undeclared runtime dependency while making unsupported input
 * fail loudly instead of silently changing a licence or normalization rule.
 */
function parse_yaml_scalar(value: string): unknown {
  const trimmed = value.trim();
  if (trimmed === '') return null;
  if (trimmed === '{}' || trimmed === '[]') return JSON.parse(trimmed);
  if (trimmed === 'true') return true;
  if (trimmed === 'false') return false;
  if (trimmed === 'null' || trimmed === '~') return null;
  if (/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(trimmed)) return Number(trimmed);
  if (trimmed.startsWith('"')) {
    return JSON.parse(trimmed);
  }
  if (trimmed.startsWith("'")) {
    if (!trimmed.endsWith("'")) throw new Error(`invalid YAML string: ${value}`);
    return trimmed.slice(1, -1).replaceAll("''", "'");
  }
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    try {
      return JSON.parse(trimmed);
    } catch {
      throw new Error(`unsupported inline YAML value: ${value}`);
    }
  }
  return trimmed;
}

function strip_yaml_comment(value: string): string {
  let quote: 'single' | 'double' | null = null;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    if (char === '"' && quote !== 'single' && value[index - 1] !== '\\') {
      quote = quote === 'double' ? null : 'double';
    } else if (char === "'" && quote !== 'double') {
      quote = quote === 'single' ? null : 'single';
    } else if (char === '#' && quote === null && (index === 0 || /\s/.test(value[index - 1]))) {
      return value.slice(0, index).trimEnd();
    }
  }
  return value;
}

function key_value(line: string): [string, string] {
  let quote: 'single' | 'double' | null = null;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"' && quote !== 'single' && line[index - 1] !== '\\') {
      quote = quote === 'double' ? null : 'double';
    } else if (char === "'" && quote !== 'double') {
      quote = quote === 'single' ? null : 'single';
    } else if (char === ':' && quote === null && (index + 1 === line.length || /\s/.test(line[index + 1]))) {
      const rawKey = line.slice(0, index).trim();
      const key = parse_yaml_scalar(rawKey);
      if (typeof key !== 'string') throw new Error(`invalid YAML key: ${rawKey}`);
      return [key, line.slice(index + 1).trim()];
    }
  }
  throw new Error(`invalid YAML mapping line: ${line}`);
}

function yaml_lines(text: string): YamlLine[] {
  return text.split(/\r?\n/).map((raw) => {
    const withoutComment = strip_yaml_comment(raw);
    const match = /^( *)/.exec(withoutComment);
    const indent = match?.[1].length ?? 0;
    return { indent, raw: withoutComment, text: withoutComment.trim() };
  });
}

function next_nonblank(lines: YamlLine[], index: number): number {
  while (index < lines.length && lines[index].text === '') index += 1;
  return index;
}

function parse_yaml_map(lines: YamlLine[], start: number, indent: number): [YamlObject, number] {
  const result: YamlObject = {};
  let index = start;

  while (index < lines.length) {
    index = next_nonblank(lines, index);
    if (index >= lines.length || lines[index].indent < indent) break;
    if (lines[index].indent > indent) {
      throw new Error(`unexpected YAML indentation: ${lines[index].raw}`);
    }

    const line = lines[index];
    const [key, rawValue] = key_value(line.text);
    if (rawValue === '|' || rawValue === '|-' || rawValue === '>' || rawValue === '>-') {
      const folded = rawValue.startsWith('>');
      const block: string[] = [];
      let cursor = index + 1;
      let contentIndent: number | null = null;
      while (cursor < lines.length) {
        const candidate = lines[cursor];
        if (candidate.text !== '' && candidate.indent <= indent) break;
        if (candidate.text !== '' && contentIndent === null) contentIndent = candidate.indent;
        block.push(candidate.text === '' ? '' : candidate.raw.slice(contentIndent ?? candidate.indent));
        cursor += 1;
      }
      const value = folded ? block.join(' ').replace(/ +/g, ' ').trim() : block.join('\n');
      result[key] = rawValue.endsWith('-') ? value : `${value}\n`;
      index = cursor;
      continue;
    }

    if (rawValue !== '') {
      result[key] = parse_yaml_scalar(rawValue);
      index += 1;
      continue;
    }

    const child = next_nonblank(lines, index + 1);
    if (child < lines.length && lines[child].indent > indent) {
      const [nested, cursor] = parse_yaml_map(lines, child, lines[child].indent);
      result[key] = nested;
      index = cursor;
    } else {
      result[key] = {};
      index += 1;
    }
  }

  return [result, index];
}

function parse_yaml(text: string): YamlObject {
  const lines = yaml_lines(text);
  const first = next_nonblank(lines, 0);
  if (first >= lines.length) return {};
  if (lines[first].indent !== 0) throw new Error('YAML document must start at indentation zero');
  if (lines[first].text === '{}') return {};
  return parse_yaml_map(lines, first, 0)[0];
}

function read_yaml(path: string): YamlObject {
  return parse_yaml(readFileSync(path, 'utf8'));
}

function read_jsonl(path: string): YamlObject[] {
  if (!existsSync(path)) return [];
  return readFileSync(path, 'utf8')
    .split(/\r?\n/)
    .filter((line) => line.trim() !== '')
    .map((line) => JSON.parse(line) as YamlObject);
}

function required_string(row: YamlObject, field: string): string {
  const value = row[field];
  if (typeof value !== 'string') throw new Error(`locale row requires string field '${field}'`);
  return value;
}

function required_number(row: YamlObject, field: string): number {
  const value = row[field];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`locale row requires numeric field '${field}'`);
  }
  return value;
}

function optional_number(row: YamlObject, field: string): number | null {
  const value = row[field];
  if (value === undefined || value === null) return null;
  return required_number(row, field);
}

function optional_string(row: YamlObject, field: string): string | null {
  const value = row[field];
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string') throw new Error(`locale row field '${field}' must be a string`);
  return value;
}

function string_list(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || !value.every((entry): entry is string => typeof entry === 'string')) {
    throw new Error(`locale row field '${field}' must be a string list`);
  }
  return value;
}

function content_hash(directory: string): string {
  const hash = createHash('sha256');
  for (const filename of ['pack.yaml', 'text_rules.yaml', 'foods.jsonl', 'aliases.jsonl', 'units.jsonl']) {
    const path = join(directory, filename);
    hash.update(filename);
    hash.update('\0');
    if (existsSync(path) && statSync(path).isFile()) hash.update(readFileSync(path));
    else hash.update('<missing>');
    hash.update('\0');
  }
  return hash.digest('hex');
}

export class LocalePack {
  readonly locale: string;
  readonly cuisine_bucket: string;
  readonly nutrition_source: string;
  readonly license: LicenseTerm;
  readonly license_note: string | null;
  readonly foods: Record<string, CanonicalFood>;
  readonly aliases: Record<string, string[]>;
  readonly negative_aliases: Record<string, string[]>;
  readonly units: Record<string, YamlObject>;
  readonly text_rules: YamlObject;

  constructor(init: {
    locale: string;
    cuisine_bucket: string;
    nutrition_source: string;
    license: LicenseTerm;
    license_note: string | null;
    foods?: Record<string, CanonicalFood>;
    aliases?: Record<string, string[]>;
    negative_aliases?: Record<string, string[]>;
    units?: Record<string, YamlObject>;
    text_rules?: YamlObject;
  }) {
    this.locale = init.locale;
    this.cuisine_bucket = init.cuisine_bucket;
    this.nutrition_source = init.nutrition_source;
    this.license = init.license;
    this.license_note = init.license_note;
    this.foods = init.foods ?? {};
    this.aliases = init.aliases ?? {};
    this.negative_aliases = init.negative_aliases ?? {};
    this.units = init.units ?? {};
    this.text_rules = init.text_rules ?? {};
  }

  get commercial_use(): CommercialUse {
    return _COMMERCIAL_USE[this.license];
  }
}

function enforce_commercial_license(pack: LocalePack): void {
  const use = pack.commercial_use;
  if (use === CommercialUse.ALLOWED) return;
  const reason = use === CommercialUse.PROHIBITED
    ? 'its data licence prohibits commercial use'
    : 'its data licence has not been verified, and unverified is treated as prohibited';
  throw new RestrictedPackError(
    `locale pack '${pack.locale}' cannot be served in commercial mode: ${reason}. `
    + `license=${pack.license} source=${JSON.stringify(pack.nutrition_source)}. `
    + `Either unset ${COMMERCIAL_MODE_ENV}, drop this pack from the deployment, `
    + 'or replace its nutrition source with one that permits commercial use.',
  );
}

const pack_cache = new Map<string, LocalePack>();

/**
 * A pack whose contents are deliberately absent from the repository.
 *
 * Restricted data (currently the TürKomp-derived Turkish rows) is fetched from
 * a licence-gated source and never committed. The pack directory, its
 * metadata and its text rules still ship, so the licence terms stay visible
 * and a missing download fails with an instruction instead of an exception
 * from a missing directory.
 */
export class PackUnavailableError extends Error {
  readonly locale: string;
  readonly directory: string;
  readonly reason: string;

  constructor(locale: string, directory: string, reason: string) {
    super(
      `locale pack '${locale}' has no food catalogue at ${directory}: ${reason}. `
      + 'Its data is licence-restricted and is not distributed with the repository; '
      + 'see docs/licensing.md for how to obtain it. Locales that do ship '
      + `(en_US, ja_JP) keep working without it.`,
    );
    this.name = 'PackUnavailableError';
    this.locale = locale;
    this.directory = directory;
    this.reason = reason;
  }
}

/** The catalogue files a pack needs before it can resolve anything. */
const CATALOGUE_FILES = ['foods.jsonl', 'aliases.jsonl', 'units.jsonl'] as const;

export function is_pack_complete(directory: string): boolean {
  return CATALOGUE_FILES.every((filename) => {
    const path = join(directory, filename);
    return existsSync(path) && statSync(path).isFile();
  });
}

function read_pack(locale: string, root?: string): LocalePack {
  const base = resolve(root ?? PACK_ROOT);
  const directory = join(base, locale);
  if (!existsSync(directory)) throw new Error(`no locale pack at ${directory}`);
  if (!is_pack_complete(directory)) {
    throw new PackUnavailableError(locale, directory, 'catalogue files are not present');
  }

  const key = `${base}\0${locale}\0${content_hash(directory)}`;
  const cached = pack_cache.get(key);
  if (cached) return cached;

  const meta = read_yaml(join(directory, 'pack.yaml'));
  const text_rules = read_yaml(join(directory, 'text_rules.yaml'));
  const locale_name = required_string(meta, 'locale');
  const pack: LocalePack = new LocalePack({
    locale: locale_name,
    cuisine_bucket: required_string(meta, 'cuisine_bucket'),
    nutrition_source: required_string(meta, 'nutrition_source'),
    license: parse_license(meta.license),
    license_note: optional_string(meta, 'license_note'),
    text_rules,
  });

  for (const row of read_jsonl(join(directory, 'foods.jsonl'))) {
    const per_100g = row.per_100g;
    if (typeof per_100g !== 'object' || per_100g === null || Array.isArray(per_100g)) {
      throw new Error("locale row requires object field 'per_100g'");
    }
    const raw_packaged = row.packaged;
    if (raw_packaged !== undefined && typeof raw_packaged !== 'boolean') {
      throw new Error("locale row field 'packaged' must be boolean");
    }
    const food = validateCanonicalFood({
      food_id: required_string(row, 'food_id'),
      name: required_string(row, 'name'),
      per_100g: makeNutrients(per_100g),
      default_serving_g: required_number(row, 'default_serving_g'),
      default_serving_name: required_string(row, 'default_serving_name'),
      source: required_string(row, 'source'),
      locale: pack.locale,
      packaged: raw_packaged ?? false,
      serving_size_g: optional_number(row, 'serving_size_g'),
      serving_size_name: optional_string(row, 'serving_size_name'),
      serving_size_source: optional_string(row, 'serving_size_source'),
      net_weight_g: optional_number(row, 'net_weight_g'),
      net_weight_source: optional_string(row, 'net_weight_source'),
      density_g_per_ml: optional_number(row, 'density_g_per_ml'),
      density_source: optional_string(row, 'density_source'),
    });
    pack.foods[food.food_id] = food;
  }

  for (const row of read_jsonl(join(directory, 'aliases.jsonl'))) {
    const food_id = required_string(row, 'food_id');
    pack.aliases[food_id] = string_list(row.alias ?? [], 'alias');
    if (row.negative_alias) pack.negative_aliases[food_id] = string_list(row.negative_alias, 'negative_alias');
  }

  for (const row of read_jsonl(join(directory, 'units.jsonl'))) {
    const unit = required_string(row, 'unit');
    const values = { ...row };
    delete values.unit;
    pack.units[unit] = values;
  }

  pack_cache.set(key, pack);
  return pack;
}

export function load(
  locale: string,
  root?: string,
  options: { commercial_mode?: boolean } = {},
): LocalePack {
  const pack = read_pack(locale, root);
  const commercial = options.commercial_mode ?? settings.commercial_mode;
  if (commercial) enforce_commercial_license(pack);
  return pack;
}

export function available(root?: string): string[] {
  const base = resolve(root ?? PACK_ROOT);
  return readdirSync(base)
    .filter((name) => existsSync(join(base, name, 'pack.yaml')))
    .sort();
}

/**
 * Locales that can serve a request right now, i.e. whose catalogue is present.
 *
 * `available` answers "which packs does the repository define" and is a
 * static question; this answers "which can this deployment actually load",
 * which depends on whether a restricted pack has been obtained.
 */
export function loadable(root?: string): string[] {
  const base = resolve(root ?? PACK_ROOT);
  return available(base).filter((name) => is_pack_complete(join(base, name)));
}
