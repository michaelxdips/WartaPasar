import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptsDir, '..');
const outDir = path.join(root, '.test-build', 'filters');
const tsc = path.join(root, 'node_modules', 'typescript', 'bin', 'tsc');

rmSync(path.join(root, '.test-build'), { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });
execFileSync(process.execPath, [tsc, path.join(root, 'lib', 'filters.ts'), '--target', 'ES2022',
  '--module', 'commonjs', '--moduleResolution', 'node', '--skipLibCheck', '--outDir', outDir],
{ cwd: root, stdio: 'inherit' });

const require = createRequire(import.meta.url);
const filters = require(path.join(outDir, 'filters.js'));
const story = { symbol: 'PASAR', topic: 'laporan', reason: 'Angka pada Judul', sources: [] };

assert.equal(filters.storyMatchesQuery(story, 'angka pada judul'), true);
assert.equal(filters.storyMatchesQuery(story, 'ANGKA PADA JUDUL'), true);
assert.equal(filters.storyMatchesQuery({ ...story, sources: [{ title: 'Suku Bunga Naik' }] }, 'suku bunga'), true);
assert.equal(filters.storyMatchesQuery(story, 'tidak ada'), false);
assert.equal(filters.storyMatchesQuery(story, '   '), true);

rmSync(path.join(root, '.test-build'), { recursive: true, force: true });
console.log('filter tests: 5 passed');
