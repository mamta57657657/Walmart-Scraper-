import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SAMPLE_RECORDS,
  TOP_CATEGORIES,
  calculateOperatingCost,
  validateRecordIntegrity,
  checkDuplicateCount
} from './scraperData';

test('sample records contain valid structured fields', () => {
  assert.ok(SAMPLE_RECORDS.length >= 2);
  const r1 = SAMPLE_RECORDS[0];
  assert.equal(r1.zipcode, '75001');
  assert.equal(r1.store_name, 'Walmart Supercenter');
  assert.equal(r1.product_title, 'Dasani Purified Water, 16.9 fl oz, 24 Pack');
  assert.equal(r1.volume_deals_description, '2 for $10');
  assert.equal(r1.volume_deals_price, '$10.00');
  assert.equal(r1.ppm, '$0.06/fl oz');
  assert.equal(validateRecordIntegrity(r1), true);
});

test('check duplicate count returns 0 on unique set', () => {
  const dups = checkDuplicateCount(SAMPLE_RECORDS);
  assert.equal(dups, 0);
});

test('top categories sum and rank ordering', () => {
  assert.equal(TOP_CATEGORIES.length, 10);
  assert.equal(TOP_CATEGORIES[0].category, 'Beverages');
  assert.equal(TOP_CATEGORIES[0].records, 94);
  assert.equal(TOP_CATEGORIES[9].category, 'Baby Care');
  assert.equal(TOP_CATEGORIES[9].records, 12);
});

test('operating cost calculation default matches baseline range', () => {
  const cost = calculateOperatingCost(1, 2);
  assert.equal(cost.breakdown.compute, '$60 - $100');
  assert.equal(cost.breakdown.proxies, '$120 - $200');
  assert.equal(cost.breakdown.storage, '$10 - $20');
  assert.equal(cost.minMonthly, 190);
  assert.equal(cost.maxMonthly, 320);
});
