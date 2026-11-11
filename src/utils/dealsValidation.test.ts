import test from 'node:test';
import assert from 'node:assert/strict';
import { FULL_DATASET, searchAndFilterRecords, exportRecordsToCSV } from './scraperData';

const REQUIRED_FIELDS_ORDER = [
  "zipcode",
  "store_name",
  "store_location",
  "store_logo",
  "store_brand",
  "category",
  "sub_category",
  "product_title",
  "weight",
  "regular_price",
  "sale_price",
  "volume_deals_description",
  "volume_deals_price",
  "digital_deals_description",
  "digital_deals_price",
  "image_url",
  "url",
  "upc",
  "gupc",
  "ppm",
  "unit_price",
  "crawl_date"
];

test('dataset contains >= 500 records and matches exact 22-field order', () => {
  assert.ok(FULL_DATASET.length >= 500, `Expected at least 500 records, got ${FULL_DATASET.length}`);

  for (let i = 0; i < Math.min(100, FULL_DATASET.length); i++) {
    const record = FULL_DATASET[i];
    const keys = Object.keys(record);
    assert.deepEqual(keys, REQUIRED_FIELDS_ORDER, `Record ${i} violates exact 22 field order`);
    assert.equal(record.gupc, "", `Record ${i} gupc must be strictly empty string`);
    assert.equal(record.unit_price, "", `Record ${i} unit_price must be strictly empty string`);
    assert.ok(record.crawl_date.length > 0, `Record ${i} crawl_date must be non-empty`);
    
    // When prices exist, they must be formatted with $
    if (record.regular_price) {
      assert.ok(record.regular_price.startsWith('$'), `Record ${i} regular_price must have $ prefix`);
    }
    if (record.sale_price) {
      assert.ok(record.sale_price.startsWith('$'), `Record ${i} sale_price must have $ prefix`);
    }
    // Approximate weight exclusion check
    assert.equal(/approx/i.test(record.weight), false, `Record ${i} should not contain approximate weight`);
  }
});

test('deals separation: volume deals vs digital coupons', () => {
  const volumeDeals = searchAndFilterRecords("", "All", "volume");
  assert.ok(volumeDeals.length > 0, "Expected volume deals to be present");
  for (const v of volumeDeals) {
    assert.ok(v.volume_deals_description.length > 0);
  }

  const digitalDeals = searchAndFilterRecords("", "All", "digital");
  assert.ok(digitalDeals.length > 0, "Expected digital deals to be present");
  for (const d of digitalDeals) {
    assert.ok(d.digital_deals_description.length > 0);
  }

  const ppmRecords = searchAndFilterRecords("", "All", "ppm");
  assert.ok(ppmRecords.length > 0, "Expected PPM records to be present");
  for (const p of ppmRecords) {
    assert.ok(p.ppm.includes('/'), `PPM ${p.ppm} must contain measurement unit /`);
  }
});

test('unavailable store-assortment items retained with empty string price/upc', () => {
  const unavailable = searchAndFilterRecords("", "All", "unavailable");
  assert.ok(unavailable.length > 0, "Expected retained unavailable store assortment items to be present");
  for (const item of unavailable) {
    assert.equal(item.regular_price, "");
    assert.equal(item.sale_price, "");
    assert.ok(item.product_title.length > 0);
    assert.ok(item.category.length > 0);
    assert.ok(item.url.length > 0);
  }
});

test('CSV export generates correct header and row count', () => {
  const csv = exportRecordsToCSV(FULL_DATASET.slice(0, 10));
  const lines = csv.split('\n');
  assert.equal(lines.length, 11);
  assert.equal(lines[0], REQUIRED_FIELDS_ORDER.join(';'));
});
