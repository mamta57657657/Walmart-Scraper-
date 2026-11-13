import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_ACCEPTANCE_GATES,
  evaluateLiveArtifacts,
} from './gateEvaluator.ts';

test('default acceptance gates keep live/Azure gates PENDING and pagination PASSED', () => {
  const report = evaluateLiveArtifacts({});
  const byId = Object.fromEntries(report.gates.map((g) => [g.id, g.status]));
  assert.equal(byId.pagination, 'PASSED');
  assert.equal(byId.coverage, 'PENDING');
  assert.equal(byId.pickup_pricing, 'PENDING');
  assert.equal(byId.recovery, 'PENDING');
  assert.equal(byId.azure, 'PENDING');
  assert.equal(report.hasVerifiedLiveUpdates, false);
  assert.equal(DEFAULT_ACCEPTANCE_GATES.length, 5);
});

test('offline fixture markers and Robot-or-human blocked captures are strictly rejected', () => {
  const report = evaluateLiveArtifacts({
    ndjsonText: JSON.stringify({
      message: 'Page 1 yielded 2 new unique records (category total: 2) OFFLINE_SPECIFICATION_FIXTURE',
    }),
    rawEvidenceText: JSON.stringify({
      endpoint: 'https://www.walmart.com/blocked?url=L2Jyb3dzZQ==',
      request: { url: 'https://www.walmart.com/blocked' },
      payload: { title: 'Robot or human?' },
    }),
  });

  const byId = Object.fromEntries(report.gates.map((g) => [g.id, g.status]));
  assert.equal(byId.coverage, 'PENDING');
  assert.equal(byId.pickup_pricing, 'PENDING');
  assert.equal(report.hasVerifiedLiveUpdates, false);
  assert.ok(report.rejectedReasons.length >= 2);
});

test('genuine live run logs, Store #4012 PICKUP capture, recovery logs, and Azure publication promote all 4 gates to PASSED', () => {
  const liveNdjson = [
    JSON.stringify({ message: '[STORE LOCK] Injecting store affinity cookies for Store #4012 (ZIP: 75001)...' }),
    JSON.stringify({ message: 'Page 1 yielded 24 new unique records (category total: 24)' }),
    JSON.stringify({ message: '[INTERRUPTION SIGNAL] Received SIGNAL_15; halting safely and preserving checkpoint & prior delivery.' }),
    JSON.stringify({ message: '[PROTECTION ACTIVE] Run interrupted (SIGNAL_15); previous committed delivery preserved intact.' }),
    JSON.stringify({ message: '[CHECKPOINT RESUME] Resuming category \'Water\' from page 2 (prior staged items: 24)' }),
    JSON.stringify({ message: 'Page 2 yielded 20 new unique records (category total: 44)' }),
    JSON.stringify({ message: '[ATOMIC PUBLISH] Promoted staging release r-2026-11-13 -> output/publication_manifest_4012.json' }),
    JSON.stringify({ message: "[AZURE BLOB PUBLISHED] Release r-2026-11-13 uploaded to container 'walmart-scraper-data' (output/publication_manifest_4012.json)" }),
  ].join('\n');

  const liveRawEvidence = JSON.stringify({
    capture_id: 'cap-live-1',
    endpoint: 'https://www.walmart.com/browse/beverages/water/976759_976782_1001438#__NEXT_DATA__',
    request: { url: 'https://www.walmart.com/browse/beverages/water/976759_976782_1001438', method: 'GET' },
    payload: {
      props: {
        pageProps: {
          locationContext: {
            intent: 'PICKUP',
            pickupStore: { storeId: '4012', postalCode: '75001' },
          },
          initialData: {
            searchResult: {
              storeId: '4012',
              fulfillmentMode: 'PICKUP',
              itemStacks: [
                {
                  items: [
                    {
                      usItemId: '10450917',
                      priceInfo: { currentPrice: { priceString: '$5.98' } },
                    },
                  ],
                },
              ],
            },
          },
        },
      },
    },
  });

  const liveManifest = JSON.stringify({
    status: 'COMMITTED',
    store_number: '4012',
    crawl_date: '2026-11-13',
    total_records: 524,
    products_sha256: 'abc123def4567890abc123def4567890abc123def4567890abc123def4567890',
    azure_container: 'walmart-scraper-data',
    azure_products_blob: 'releases/r-2026-11-13/walmart_4012_2026-11-13.json',
    azure_evidence_blob: 'releases/r-2026-11-13/raw_evidence_4012_2026-11-13.jsonl',
  });

  const report = evaluateLiveArtifacts({
    ndjsonText: liveNdjson,
    rawEvidenceText: liveRawEvidence,
    manifestTexts: [liveManifest],
    evaluatedAt: '2026-11-13T04:00:00Z',
  });

  const byId = Object.fromEntries(report.gates.map((g) => [g.id, g.status]));
  assert.equal(byId.pagination, 'PASSED');
  assert.equal(byId.coverage, 'PASSED');
  assert.equal(byId.pickup_pricing, 'PASSED');
  assert.equal(byId.recovery, 'PASSED');
  assert.equal(byId.azure, 'PASSED');
  assert.equal(report.hasVerifiedLiveUpdates, true);
  assert.equal(report.rejectedReasons.length, 0);
});
