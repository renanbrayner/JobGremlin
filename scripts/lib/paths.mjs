// Shared path contract for the copied Node flow scripts.
//
// The parallel workspace owns config/, data/ and output/. The installed
// career-ops checkout is only ever read. Override any path with the matching
// CAREER_OPS_* environment variable, or put it in config/career-ops.env.

import { existsSync, mkdirSync, readFileSync, realpathSync } from 'node:fs';
import { basename, dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_HOME = resolve(HERE, '../..');

function expand(raw, env) {
  let text = String(raw).replace(
    /\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)/g,
    (_match, braced, bare) => env[braced || bare] ?? '',
  );
  if (text === '~' || text.startsWith('~/')) {
    text = `${env.HOME || ''}${text.slice(1)}`;
  }
  return text;
}

function parseEnvFile(path) {
  const values = {};
  for (const line of readFileSync(path, 'utf-8').split('\n')) {
    let text = line.trim();
    if (!text || text.startsWith('#')) continue;
    if (text.startsWith('export ')) text = text.slice(7).trim();
    const at = text.indexOf('=');
    if (at < 0) continue;
    const key = text.slice(0, at).trim();
    let value = text.slice(at + 1).trim();
    if (value.length >= 2 && value[0] === value[value.length - 1] && ['"', "'"].includes(value[0])) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return values;
}

function loadEnvFile(env) {
  const home = expand(env.CAREER_OPS_HOME || DEFAULT_HOME, env);
  const configDir = expand(env.CAREER_OPS_CONFIG || resolve(home, 'config'), env);
  const envFile = expand(env.CAREER_OPS_ENV_FILE || resolve(configDir, 'career-ops.env'), {
    ...env,
    CAREER_OPS_HOME: home,
  });
  if (!existsSync(envFile)) return;

  const context = { ...env, CAREER_OPS_HOME: home };
  for (const [key, raw] of Object.entries(parseEnvFile(envFile))) {
    if (key in env) continue;
    env[key] = expand(raw, context);
    context[key] = env[key];
  }
}

function pathFrom(env, key, fallback) {
  return resolve(expand(env[key] || fallback, env));
}

const env = { ...process.env };
loadEnvFile(env);

export const WORKSPACE_ROOT = pathFrom(env, 'CAREER_OPS_HOME', DEFAULT_HOME);
export const UPSTREAM_ROOT = pathFrom(env, 'CAREER_OPS_UPSTREAM', '~/.local/share/career-ops');
export const CONFIG_DIR = pathFrom(env, 'CAREER_OPS_CONFIG', resolve(WORKSPACE_ROOT, 'config'));
export const DATA_DIR = pathFrom(env, 'CAREER_OPS_DATA', resolve(WORKSPACE_ROOT, 'data'));
export const OUTPUT_DIR = pathFrom(env, 'CAREER_OPS_OUTPUT', resolve(WORKSPACE_ROOT, 'output'));
export const SCRIPTS_DIR = pathFrom(env, 'CAREER_OPS_SCRIPTS', resolve(WORKSPACE_ROOT, 'scripts'));

function canonical(candidatePath) {
  let probe = resolve(candidatePath);
  const tail = [];
  while (!existsSync(probe)) {
    tail.unshift(basename(probe));
    const parent = dirname(probe);
    if (parent === probe) break;
    probe = parent;
  }
  try {
    return resolve(realpathSync(probe), ...tail);
  } catch {
    return resolve(candidatePath);
  }
}

function inside(child, parent) {
  const candidate = canonical(child);
  const root = canonical(parent);
  return candidate === root || candidate.startsWith(`${root}${sep}`);
}

export function assertNotUpstream(path, label = 'write') {
  const candidate = resolve(path);
  if (inside(candidate, UPSTREAM_ROOT)) {
    throw new Error(
      `refusing to ${label} at ${candidate}: it is inside the read-only upstream checkout ${UPSTREAM_ROOT}`,
    );
  }
  return candidate;
}

// A misconfigured workspace must fail before any command can write into the
// installed career-ops checkout.
for (const [name, directory] of [
  ['CAREER_OPS_CONFIG', CONFIG_DIR],
  ['CAREER_OPS_DATA', DATA_DIR],
  ['CAREER_OPS_OUTPUT', OUTPUT_DIR],
]) {
  if (inside(directory, UPSTREAM_ROOT)) {
    throw new Error(
      `${name}=${directory} is inside the read-only upstream checkout ${UPSTREAM_ROOT}`,
    );
  }
}

export function readConfig(name) {
  const workspace = resolve(CONFIG_DIR, name);
  if (existsSync(workspace)) return workspace;
  const upstream = resolve(UPSTREAM_ROOT, 'config', name);
  return existsSync(upstream) ? upstream : workspace;
}

export function readData(name) {
  const workspace = resolve(DATA_DIR, name);
  if (existsSync(workspace)) return workspace;
  const upstream = resolve(UPSTREAM_ROOT, 'data', name);
  return existsSync(upstream) ? upstream : workspace;
}

export function ensureDir(path) {
  mkdirSync(path, { recursive: true });
  return path;
}
