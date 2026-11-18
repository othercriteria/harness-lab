'use strict';

function currentRelease(records, channel) {
  const latest = new Map();
  for (const row of records) {
    if (row.channel !== channel) continue;
    const previous = latest.get(row.build);
    if (previous === undefined || row.revision > previous.revision) {
      latest.set(row.build, row);
    }
  }

  let current = null;
  for (const row of latest.values()) {
    if (row.state === 'published' && (current === null || row.build > current)) {
      current = row.build;
    }
  }
  return current;
}

module.exports = { currentRelease };
