'use strict';
const { isDeepStrictEqual } = require('node:util');
const { currentRelease } = require('/workspace/current-release.cjs');
const { records, channel } = require('/evaluation/input.json');
const values = structuredClone(records);
const members = records.slice();
const result = currentRelease(records, channel);
process.stdout.write(JSON.stringify({
  value: [typeof result, result],
  unchanged: isDeepStrictEqual(records, values) && members.every((r, i) => r === records[i]),
}));
