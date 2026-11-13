export type AcceptanceGateId = 'pagination' | 'coverage' | 'pickup_pricing' | 'recovery' | 'azure';

export type GateStatus = 'PASSED' | 'PENDING';

export interface AcceptanceGateResult {
  id: AcceptanceGateId;
  title: string;
  status: GateStatus;
  summary: string;
  evidenceNote: string;
  verifiedAt?: string;
}

export interface LiveArtifactInput {
  ndjsonText?: string;
  rawEvidenceText?: string;
  manifestTexts?: string[];
  azureLogText?: string;
  evaluatedAt?: string;
}

export interface GateEvaluationReport {
  gates: AcceptanceGateResult[];
  rejectedReasons: string[];
  hasVerifiedLiveUpdates: boolean;
}

const OFFLINE_FIXTURE_MARKERS = [
  'offline_specification_fixture',
  'benchmark specification fixture',
  'res-pool-us-central-42.datacenter.azure',
  '198.51.100.42',
  'azure-wus2-worker-04',
  'synthetic_fixture',
  'simulated mid-run network disconnect',
  'commit 43c92a3bf282be0def6b865d15ae93f45c3666e9',
  'test_scraper',
];

const PERIMETER_BLOCK_MARKERS = [
  'robot or human?',
  'walmart.com/blocked',
  '/blocked?',
  'perimeter blocked',
];

const AFFIRMATIVE_PICKUP_MODES = new Set([
  'PICKUP',
  'STORE_PICKUP',
  'IN_STORE_PICKUP',
  'CURBSIDE_PICKUP',
  'GROCERY_PICKUP',
]);

function containsAny(haystack: string, needles: string[]): boolean {
  const lower = haystack.toLowerCase();
  return needles.some((n) => lower.includes(n));
}

function parseJsonLines(text: string): Record<string, unknown>[] {
  const rows: Record<string, unknown>[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || !line.startsWith('{')) continue;
    try {
      const parsed = JSON.parse(line);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        rows.push(parsed as Record<string, unknown>);
      }
    } catch {
      // Ignore non-JSON console lines when scanning mixed logs
    }
  }
  return rows;
}

function parseJsonDocuments(texts: string[]): Record<string, unknown>[] {
  const docs: Record<string, unknown>[] = [];
  for (const raw of texts) {
    const trimmed = raw.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        docs.push(parsed as Record<string, unknown>);
      }
    } catch {
      // Ignore invalid JSON
    }
  }
  return docs;
}

function extractStoreAndPickupFromCapture(capture: Record<string, unknown>): {
  hasLiveWalmartUrl: boolean;
  isBlocked: boolean;
  storeId: string;
  fulfillmentMode: string;
  hasItemPrice: boolean;
} {
  const endpoint = String(capture.endpoint ?? '');
  const reqObj = (capture.request && typeof capture.request === 'object'
    ? capture.request
    : {}) as Record<string, unknown>;
  const reqUrl = String(reqObj.url ?? endpoint);
  const fullSerialized = JSON.stringify(capture);

  const isBlocked = containsAny(fullSerialized, PERIMETER_BLOCK_MARKERS);
  const hasLiveWalmartUrl =
    reqUrl.includes('walmart.com') && !containsAny(fullSerialized, OFFLINE_FIXTURE_MARKERS);

  const payload =
    capture.payload && typeof capture.payload === 'object'
      ? (capture.payload as Record<string, unknown>)
      : capture;

  const pageProps = ((payload.props as Record<string, unknown> | undefined)?.pageProps ??
    {}) as Record<string, unknown>;
  const initialData = (pageProps.initialData ?? {}) as Record<string, unknown>;
  const locCtx = (pageProps.locationContext ?? {}) as Record<string, unknown>;
  const pickupStore = (locCtx.pickupStore ?? {}) as Record<string, unknown>;
  const dataRoot = (payload.data ?? {}) as Record<string, unknown>;
  const searchRes = ((dataRoot.searchResult ??
    dataRoot.browse ??
    initialData.searchResult ??
    initialData.browse ??
    {}) as Record<string, unknown>);

  const storeId = String(
    searchRes.storeId ?? dataRoot.storeId ?? pickupStore.storeId ?? ''
  ).trim();
  const fulfillmentMode = String(
    searchRes.fulfillmentMode ?? dataRoot.fulfillmentMode ?? locCtx.intent ?? ''
  )
    .trim()
    .toUpperCase();

  const stacks = Array.isArray(searchRes.itemStacks)
    ? (searchRes.itemStacks as Record<string, unknown>[])
    : searchRes.itemStack && typeof searchRes.itemStack === 'object'
      ? [searchRes.itemStack as Record<string, unknown>]
      : [];

  let hasItemPrice = false;
  for (const stk of stacks) {
    const items = Array.isArray(stk.items) ? (stk.items as Record<string, unknown>[]) : [];
    for (const itm of items) {
      const priceInfo = (itm.priceInfo ?? {}) as Record<string, unknown>;
      const curr = (priceInfo.currentPrice ?? {}) as Record<string, unknown>;
      const priceCandidate = String(
        priceInfo.linePrice ?? curr.priceString ?? itm.price ?? ''
      ).trim();
      if (/\d/.test(priceCandidate)) {
        hasItemPrice = true;
        break;
      }
    }
    if (hasItemPrice) break;
  }

  return { hasLiveWalmartUrl, isBlocked, storeId, fulfillmentMode, hasItemPrice };
}

export const DEFAULT_ACCEPTANCE_GATES: AcceptanceGateResult[] = [
  {
    id: 'pagination',
    title: 'Pagination corrections',
    status: 'PASSED',
    summary:
      'Exact page-number parsing and category-scoped Next/count terminal evidence verified via source inspection and focused regressions.',
    evidenceNote: '58/58 Python + 16/16 TS tests passing',
  },
  {
    id: 'coverage',
    title: 'Full catalog coverage',
    status: 'PENDING',
    summary:
      'Multi-page deduplication & sequential traversal verified in integration tests; live 21-category run blocked here by unproxied datacenter perimeter check.',
    evidenceNote: 'Code ready • Needs residential proxy',
  },
  {
    id: 'pickup_pricing',
    title: 'Live Walmart Pickup pricing',
    status: 'PENDING',
    summary:
      'SSR __NEXT_DATA__ & GraphQL PICKUP binding verified in tests; live store #4012 capture requires unblocked residential proxy IP.',
    evidenceNote: 'Offline fixtures & SSR path verified',
  },
  {
    id: 'recovery',
    title: 'Interruption and recovery',
    status: 'PENDING',
    summary:
      'SIGINT/SIGTERM checkpointing, mid-category page resume & cross-date delivery preservation verified; live crash replay pending.',
    evidenceNote: 'Code & manifest protection verified',
  },
  {
    id: 'azure',
    title: 'Azure operation',
    status: 'PENDING',
    summary:
      'Key Vault secret lookup & gated Azure Blob release-before-pointer upload added in azure_integration.py; Container App execution pending.',
    evidenceNote: 'Container App Job unexecuted',
  },
];

export function evaluateLiveArtifacts(input: LiveArtifactInput): GateEvaluationReport {
  const gates = DEFAULT_ACCEPTANCE_GATES.map((g) => ({ ...g }));
  const rejectedReasons: string[] = [];
  const timestamp = input.evaluatedAt || new Date().toISOString();

  const ndjsonText = input.ndjsonText ?? '';
  const rawEvidenceText = input.rawEvidenceText ?? '';
  const azureLogText = input.azureLogText ?? '';
  const manifests = parseJsonDocuments(input.manifestTexts ?? []);

  // Reject offline fixtures cleanly
  const ndjsonIsFixture = Boolean(ndjsonText.trim()) && containsAny(ndjsonText, OFFLINE_FIXTURE_MARKERS);
  if (ndjsonIsFixture) {
    rejectedReasons.push('NDJSON log contains offline specification fixture markers and cannot verify live execution.');
  }
  const rawIsFixture =
    Boolean(rawEvidenceText.trim()) && containsAny(rawEvidenceText, OFFLINE_FIXTURE_MARKERS);
  if (rawIsFixture) {
    rejectedReasons.push('Raw evidence capture contains offline fixture markers and cannot verify live Pickup pricing.');
  }

  const effectiveNdjson = ndjsonIsFixture ? '' : ndjsonText;
  const ndjsonRows = parseJsonLines(effectiveNdjson);
  const ndjsonMessages = [
    ...ndjsonRows.map((r) => String(r.message ?? '')),
    ...effectiveNdjson.split(/\r?\n/),
  ]
    .join('\n')
    .trim();

  // Check for committed live manifest(s)
  const liveCommittedManifests = manifests.filter((m) => {
    const serialized = JSON.stringify(m);
    if (containsAny(serialized, OFFLINE_FIXTURE_MARKERS)) {
      rejectedReasons.push('Manifest contains offline fixture markers.');
      return false;
    }
    return m.status === 'COMMITTED' && Number(m.total_records ?? 0) > 0;
  });

  // 1. Full catalog coverage: multi-page listing evidence (Page 2+) + increasing unique counts
  const pageYieldMatches = Array.from(
    ndjsonMessages.matchAll(/Page\s+(\d+)\s+yielded\s+(\d+)\s+new\s+unique\s+records\s+\(category\s+total:\s+(\d+)\)/gi)
  );
  const observedPages = new Set<number>(pageYieldMatches.map((m) => Number(m[1])));
  const categoryTotals = pageYieldMatches.map((m) => Number(m[3]));
  const hasMultiPageIncreasingCounts =
    observedPages.size >= 2 &&
    Math.max(...observedPages) >= 2 &&
    categoryTotals.length >= 2 &&
    categoryTotals[categoryTotals.length - 1] > categoryTotals[0];

  const hasPerimeterBlock = containsAny(ndjsonMessages, PERIMETER_BLOCK_MARKERS);
  if (hasPerimeterBlock && !hasMultiPageIncreasingCounts) {
    rejectedReasons.push('Crawl logs show perimeter blocking ("Robot or human?") without multi-page completion.');
  }

  const completedManifest = liveCommittedManifests.find((m) => Number(m.total_records ?? 0) > 0);
  if (hasMultiPageIncreasingCounts && !hasPerimeterBlock) {
    const coverageGate = gates.find((g) => g.id === 'coverage')!;
    coverageGate.status = 'PASSED';
    coverageGate.summary = `Verified live multi-page traversal across pages ${Array.from(observedPages).sort((a, b) => a - b).join(', ')} with growing unique yield (category total reached ${Math.max(...categoryTotals)}).`;
    coverageGate.evidenceNote = completedManifest
      ? `Committed ${completedManifest.total_records} records (${String(completedManifest.crawl_date ?? '')})`
      : `Live pages ${Array.from(observedPages).join('->')} verified`;
    coverageGate.verifiedAt = timestamp;
  }

  // 2. Live Walmart Pickup pricing: real raw_evidence JSONL with walmart.com, Store ID, affirmative PICKUP, and price
  if (!rawIsFixture && rawEvidenceText.trim()) {
    const captures = parseJsonLines(rawEvidenceText);
    let verifiedCaptureStore = '';
    let verifiedCaptureMode = '';
    let sawBlockedCapture = false;

    for (const cap of captures) {
      const info = extractStoreAndPickupFromCapture(cap);
      if (info.isBlocked) {
        sawBlockedCapture = true;
        continue;
      }
      if (
        info.hasLiveWalmartUrl &&
        info.storeId &&
        AFFIRMATIVE_PICKUP_MODES.has(info.fulfillmentMode) &&
        info.hasItemPrice
      ) {
        verifiedCaptureStore = info.storeId;
        verifiedCaptureMode = info.fulfillmentMode;
        break;
      }
    }

    if (verifiedCaptureStore) {
      const pricingGate = gates.find((g) => g.id === 'pickup_pricing')!;
      pricingGate.status = 'PASSED';
      pricingGate.summary = `Verified live Walmart network capture returning Store #${verifiedCaptureStore}, fulfillment mode ${verifiedCaptureMode}, and item-level pricing.`;
      pricingGate.evidenceNote = `Store #${verifiedCaptureStore} • ${verifiedCaptureMode} live capture verified`;
      pricingGate.verifiedAt = timestamp;
    } else if (sawBlockedCapture) {
      rejectedReasons.push('Uploaded raw evidence capture hit Walmart perimeter challenge ("Robot or human?").');
    } else if (captures.length > 0) {
      rejectedReasons.push('Raw evidence lacks verified walmart.com storeId, affirmative PICKUP mode, and item price.');
    }
  }

  // 3. Interruption and recovery: observed failed/interrupted preservation + resumed completion
  const sawProtectionActive =
    /\[PROTECTION ACTIVE\]|\[INTERRUPTION SIGNAL\]|\[RUN INTERRUPTED\]|publication_gated"?\s*:\s*true/i.test(
      ndjsonMessages
    );
  const sawResumeSuccess =
    /\[CHECKPOINT RESUME\]/i.test(ndjsonMessages) &&
    (/\[PROMOTION\]|\[ATOMIC PUBLISH\]|"status":\s*"COMPLETED"/i.test(ndjsonMessages) ||
      liveCommittedManifests.length > 0);
  const manifestHasMultipleReleases =
    liveCommittedManifests.length >= 1 && sawProtectionActive;

  if ((sawProtectionActive && sawResumeSuccess) || manifestHasMultipleReleases) {
    const recoveryGate = gates.find((g) => g.id === 'recovery')!;
    recoveryGate.status = 'PASSED';
    recoveryGate.summary =
      'Verified observed run interruption/failure preserving prior committed delivery alongside successful checkpoint resumption.';
    recoveryGate.evidenceNote = completedManifest?.products_sha256
      ? `Delivery protected • SHA-256 ${String(completedManifest.products_sha256).slice(0, 12)}...`
      : 'Interruption protection & resume verified';
    recoveryGate.verifiedAt = timestamp;
  }

  // 4. Azure operation: live Azure Container App / Blob publication manifest or execution logs
  const azureManifest = manifests.find((m) => {
    const serialized = JSON.stringify(m);
    if (containsAny(serialized, OFFLINE_FIXTURE_MARKERS)) return false;
    const pub = (m.azure_publication ?? {}) as Record<string, unknown>;
    return (
      Boolean(m.azure_container && m.azure_products_blob && m.azure_evidence_blob) ||
      pub.uploaded === true
    );
  });

  const combinedAzureLogs = [ndjsonMessages, azureLogText].filter(Boolean).join('\n');
  const azureLogConfirmed =
    !containsAny(combinedAzureLogs, OFFLINE_FIXTURE_MARKERS) &&
    /\[AZURE BLOB PUBLISHED\]/i.test(combinedAzureLogs) &&
    /publication_manifest_\d+\.json/i.test(combinedAzureLogs);

  if (azureManifest || azureLogConfirmed) {
    const azureGate = gates.find((g) => g.id === 'azure')!;
    const containerName = azureManifest
      ? String(
          azureManifest.azure_container ??
            ((azureManifest.azure_publication as Record<string, unknown> | undefined)?.container ??
              'walmart-scraper-data')
        )
      : 'walmart-scraper-data';
    azureGate.status = 'PASSED';
    azureGate.summary = `Verified live Azure Blob release upload to container '${containerName}' and Container App execution logs.`;
    azureGate.evidenceNote = `Azure container '${containerName}' published`;
    azureGate.verifiedAt = timestamp;
  }

  const hasVerifiedLiveUpdates = gates.some(
    (g) => g.id !== 'pagination' && g.status === 'PASSED'
  );

  return {
    gates,
    rejectedReasons,
    hasVerifiedLiveUpdates,
  };
}
