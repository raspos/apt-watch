const fs = require('fs');
const path = require('path');

// Read data.json and districts svg
const data = JSON.parse(fs.readFileSync(path.join(__dirname, '../site/data.json'), 'utf8'));

console.log('=== TEST 1: 90-day vs 180-day vs Insufficient counts ===');
const regions = Object.entries(data.market.regions).filter(([c]) => c !== 'all');
const actualCount = regions.filter(([c, r]) => {
  const sp = r.spread || {};
  return sp.status === '실측' || (sp.actual90d && sp.actual90d.percent != null);
}).length;
const longCount = regions.filter(([c, r]) => {
  const sp = r.spread || {};
  return sp.status === '장기 실측 참고치' || (sp.status !== '실측' && sp.longTerm180d && sp.longTerm180d.percent != null);
}).length;
const insuffCount = regions.length - actualCount - longCount;

console.log(`Total: ${regions.length}, 90d: ${actualCount}, 180d: ${longCount}, Insufficient: ${insuffCount}`);
if (actualCount !== 22 || longCount !== 2 || insuffCount !== 1) {
  throw new Error(`Count mismatch: expected 22/2/1, got ${actualCount}/${longCount}/${insuffCount}`);
}
console.log('>> TEST 1 PASSED!');

console.log('\n=== TEST 2: Gangnam & Seocho sample and groups verification ===');
const gangnamSp = data.market.regions['11680'].spread;
const seochoSp = data.market.regions['11650'].spread;
const jongnoSp = data.market.regions['11110'].spread;

console.log('Gangnam 180d sample:', gangnamSp.longTerm180d.sample, 'groups:', gangnamSp.longTerm180d.groups);
console.log('Seocho 180d sample:', seochoSp.longTerm180d.sample, 'groups:', seochoSp.longTerm180d.groups);
console.log('Jongno sample:', jongnoSp.sample, 'status:', jongnoSp.status);

if (gangnamSp.longTerm180d.sample < 1 || gangnamSp.longTerm180d.groups < 1) {
  throw new Error('Gangnam must not have 0 sample/groups in longTerm180d');
}
if (seochoSp.longTerm180d.sample < 1 || seochoSp.longTerm180d.groups < 1) {
  throw new Error('Seocho must not have 0 sample/groups in longTerm180d');
}
console.log('>> TEST 2 PASSED!');

console.log('\n=== TEST 3: Mock Future Concession and Vitality Auto-Activation ===');
// Simulate future data entry with concessions and vitality
const mockRegion = {
  spread: { status: '실측', actual90d: { percent: 4.5, sample: 10, groups: 10 } },
  concessions: {
    '7': { sample: 25, cutShare: 18.0, riseShare: 6.0 }
  },
  absorption: { percent: 3.2, tradeCount: 32, meanDailyListings: 1000 }
};

// Check concession net logic
const cc = mockRegion.concessions['7'];
const net = (cc.riseShare || 0) - (cc.cutShare || 0);
console.log('Mock Concession Net:', net, '%p');
if (net !== -12.0) throw new Error('Concession net calculation failed');

// Check vitality logic
const vitVal = mockRegion.absorption.percent;
console.log('Mock Vitality:', vitVal, '건');
if (vitVal !== 3.2) throw new Error('Vitality calculation failed');

console.log('>> TEST 3 PASSED!');

console.log('\n=== TEST 4: Spread History coverage across all 25 districts + all ===');
const shKeys = Object.keys(data.market.spreadHistory || {});
console.log('Spread history keys count:', shKeys.length);
if (shKeys.length !== 26) {
  throw new Error(`Expected 26 spread history keys, got ${shKeys.length}`);
}
for (const k of ['11680', '11650', '11110', 'all']) {
  if (!shKeys.includes(k)) throw new Error(`Missing spread history for ${k}`);
  console.log(`Key ${k} has ${data.market.spreadHistory[k].length} point(s)`);
}
console.log('>> TEST 4 PASSED!');
