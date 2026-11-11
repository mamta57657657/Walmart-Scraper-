import test from 'node:test';
import assert from 'node:assert/strict';
import { ALL_USA_STORES, searchStores, getStoreByNumber, exportStoresToCSV, US_REGIONS } from './usStoresData.js';

test('ALL_USA_STORES covers all 50 US States plus DC', () => {
  const uniqueStates = new Set(ALL_USA_STORES.map(s => s.state_code));
  // 50 states + DC = 51 jurisdictions
  assert.ok(uniqueStates.size >= 51, `Expected at least 51 jurisdictions, got ${uniqueStates.size}`);
  
  // Verify key states from all 4 regions
  const mustHave = ['CA', 'NY', 'TX', 'FL', 'IL', 'WA', 'AK', 'HI', 'DC', 'WY', 'ME', 'AR'];
  for (const code of mustHave) {
    assert.ok(uniqueStates.has(code), `Missing state code: ${code}`);
  }
});

test('ALL_USA_STORES has valid required attributes and no empty strings', () => {
  for (const store of ALL_USA_STORES) {
    assert.ok(store.store_number && store.store_number.trim().length > 0, `Invalid store number in ${JSON.stringify(store)}`);
    assert.ok(store.name && store.name.trim().length > 0);
    assert.ok(store.state && store.state.trim().length > 0);
    assert.ok(store.state_code && store.state_code.length === 2);
    assert.ok(store.city && store.city.trim().length > 0);
    assert.ok(store.zipcode && /^\d{5}$/.test(store.zipcode), `Invalid ZIP code ${store.zipcode} for store ${store.store_number}`);
    assert.ok(store.address && store.address.trim().length > 0);
    assert.ok(store.phone && store.phone.trim().length > 0);
    assert.ok(['Supercenter', 'Neighborhood Market'].includes(store.type));
    assert.ok(['Northeast', 'Midwest', 'South', 'West'].includes(store.region));
    assert.ok(store.hours && store.hours.trim().length > 0);
    assert.ok(store.timezone && store.timezone.trim().length > 0);
  }
});

test('searchStores filters correctly across regions and queries', () => {
  // Query by state code filter
  const caResults = searchStores('', 'All', 'CA');
  assert.ok(caResults.length >= 1);
  assert.ok(caResults.every(s => s.state_code === 'CA'));

  // Query by city
  const dallasResults = searchStores('Dallas');
  assert.ok(dallasResults.length >= 1);
  assert.equal(dallasResults[0].city, 'Dallas');

  // Query by store number
  const store5154 = searchStores('5154');
  assert.equal(store5154.length, 1);
  assert.equal(store5154[0].store_number, '5154');

  // Filter with region
  const westResults = searchStores('', 'West');
  assert.ok(westResults.length > 0);
  assert.ok(westResults.every(s => s.region === 'West'));
});

test('getStoreByNumber retrieves correct store or returns default store #4012 safely', () => {
  const store100 = getStoreByNumber('100');
  assert.equal(store100.store_number, '100');
  assert.equal(store100.city, 'Bentonville');

  const unknown = getStoreByNumber('99999999');
  assert.equal(unknown.store_number, '4012'); // Safe fallback
});

test('exportStoresToCSV generates valid RFC 4180 CSV with header row', () => {
  const csv = exportStoresToCSV(ALL_USA_STORES);
  const lines = csv.trim().split('\n');
  assert.equal(lines.length, ALL_USA_STORES.length + 1); // 1 header + stores
  assert.ok(lines[0].startsWith('"store_number"'));
});

