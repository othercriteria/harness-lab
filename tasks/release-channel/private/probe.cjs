'use strict';
const inputs = require('/evaluation/inputs.json');
const { currentRelease } = require('/workspace/current-release.cjs');
const answers = inputs.map(({ records, channel }) => {
  for (const row of records) Object.freeze(row);
  return currentRelease(Object.freeze(records), channel);
});
process.stdout.write(JSON.stringify(answers.map(value => [typeof value, value])));
