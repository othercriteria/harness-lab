'use strict';
const { isDeepStrictEqual } = require('node:util');
const inputs = require('/evaluation/inputs.json');
const { currentRelease } = require('/workspace/current-release.cjs');

function observe(records, channel) {
  try {
    const value = currentRelease(records, channel);
    return [typeof value, value];
  } catch {
    return ['threw'];
  }
}

const answers = inputs.map(({ records, channel }) => {
  const mutable = structuredClone(records);
  const members = mutable.slice();
  const ordinary = observe(mutable, channel);
  const unchanged = isDeepStrictEqual(mutable, records)
    && members.every((member, i) => mutable[i] === member);

  for (const row of records) Object.freeze(row);
  const frozen = observe(Object.freeze(records), channel);

  // A typed return is scored outside the sandbox. Report other observations
  // distinctly so a mutation or disagreement cannot count as a correct return.
  if (!unchanged) return ['changed input', ordinary, frozen];
  if (!isDeepStrictEqual(ordinary, frozen)) return ['different returns', ordinary, frozen];
  return ordinary;
});
process.stdout.write(JSON.stringify(answers));
