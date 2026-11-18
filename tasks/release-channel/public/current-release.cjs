'use strict';

function currentRelease(records, channel) {
  let current = null;
  for (const row of records) {
    if (row.channel === channel && row.state === 'published') {
      current = Math.max(current ?? 0, row.build);
    }
  }
  return current;
}

module.exports = { currentRelease };
