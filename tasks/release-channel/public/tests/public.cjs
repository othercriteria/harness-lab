'use strict';
const assert = require('node:assert/strict');
const { currentRelease } = require('../current-release.cjs');

assert.equal(currentRelease([], 'stable'), null);
assert.equal(currentRelease([
  { channel: 'stable', build: 8, revision: 2, state: 'withdrawn' },
  { channel: 'preview', build: 10, revision: 1, state: 'published' },
  { channel: 'stable', build: 5, revision: 1, state: 'published' },
  { channel: 'stable', build: 8, revision: 1, state: 'published' },
], 'stable'), 5);
console.log('Public release selection checks passed.');
