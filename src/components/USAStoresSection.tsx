import React, { useState, useMemo } from 'react';
import {
  Store,
  MapPin,
  Search,
  CheckCircle2,
  Download,
  Copy,
  Clock,
  Phone,
  Layers,
  Globe,
  Sliders,
  ExternalLink,
  ShieldCheck,
  Zap,
  Check,
  ArrowRight,
  Database,
  Terminal,
  FileText,
  Table as TableIcon,
  LayoutGrid
} from 'lucide-react';
import {
  ALL_USA_STORES,
  US_REGIONS,
  searchStores,
  exportStoresToCSV,
  USStoreLocation
} from '../utils/usStoresData';

export interface USAStoresSectionProps {
  selectedStoreNumber: string;
  onSelectStore: (store: USStoreLocation) => void;
  onNavigateTab?: (tab: 'dashboard' | 'evidence' | 'dataset' | 'runner' | 'code' | 'dossier') => void;
}

export function USAStoresSection({
  selectedStoreNumber,
  onSelectStore,
  onNavigateTab
}: USAStoresSectionProps) {
  const [selectedRegion, setSelectedRegion] = useState<string>('All');
  const [selectedStateCode, setSelectedStateCode] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [copiedStoreNum, setCopiedStoreNum] = useState<string | null>(null);
  const [appliedFeedbackStore, setAppliedFeedbackStore] = useState<USStoreLocation | null>(null);
  const [viewFormat, setViewFormat] = useState<'matrix' | 'cards'>('matrix');
  const [autoApplyOnStateClick, setAutoApplyOnStateClick] = useState<boolean>(true);

  // Group stores by state code
  const uniqueStates = useMemo(() => {
    const map = new Map<string, { code: string; name: string; region: string; count: number; defaultStore: USStoreLocation }>();
    for (const s of ALL_USA_STORES) {
      if (!map.has(s.state_code)) {
        map.set(s.state_code, { code: s.state_code, name: s.state, region: s.region, count: 1, defaultStore: s });
      } else {
        map.get(s.state_code)!.count += 1;
      }
    }
    return Array.from(map.values()).sort((a, b) => a.code.localeCompare(b.code));
  }, []);

  // Filtered store results
  const filteredStores = useMemo(() => {
    return searchStores(searchQuery, selectedRegion, selectedStateCode);
  }, [searchQuery, selectedRegion, selectedStateCode]);

  const activeStore = useMemo(() => {
    return ALL_USA_STORES.find(s => s.store_number === selectedStoreNumber) || ALL_USA_STORES[1]; // default TX
  }, [selectedStoreNumber]);

  // Selected state store preview
  const selectedStateStore = useMemo(() => {
    if (selectedStateCode === 'All') return null;
    return ALL_USA_STORES.find(s => s.state_code === selectedStateCode) || null;
  }, [selectedStateCode]);

  const handleApplyStore = (store: USStoreLocation) => {
    onSelectStore(store);
    setAppliedFeedbackStore(store);
    setTimeout(() => {
      setAppliedFeedbackStore(null);
    }, 4500);
  };

  const handleStateClick = (stateCode: string) => {
    setSelectedStateCode(stateCode);
    if (autoApplyOnStateClick && stateCode !== 'All') {
      const target = ALL_USA_STORES.find(s => s.state_code === stateCode);
      if (target) {
        handleApplyStore(target);
      }
    }
  };

  const handleDownloadCSV = () => {
    const csv = exportStoresToCSV(filteredStores);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `walmart_usa_all_states_stores_${filteredStores.length}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadJSON = () => {
    const data = JSON.stringify(filteredStores, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `walmart_usa_all_states_stores_${filteredStores.length}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyConfigSnippet = (store: USStoreLocation) => {
    const snippet = `StoreConfig(store_number="${store.store_number}", zipcode="${store.zipcode}", name="${store.name}", address="${store.address}", state_code="${store.state_code}", city="${store.city}")`;
    navigator.clipboard.writeText(snippet);
    setCopiedStoreNum(store.store_number);
    setTimeout(() => setCopiedStoreNum(null), 2000);
  };

  return (
    <div className="max-w-[1410px] mx-auto p-4 md:p-6 space-y-6">
      {/* 1. Header & Summary Stats */}
      <div className="bg-white rounded-lg border border-slate-300 shadow-sm p-4 md:p-5">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-200 pb-4">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="bg-[#0071dc] text-white font-mono text-[11px] font-bold px-2 py-0.5 rounded">
                ALL 50 USA STATES + DC
              </span>
              <span className="bg-emerald-600 text-white text-[11px] font-semibold px-2 py-0.5 rounded flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                Live Location Targeting Active
              </span>
              <span className="bg-purple-100 text-purple-800 text-[11px] font-semibold px-2 py-0.5 rounded border border-purple-300">
                Azure Multi-Worker Ready
              </span>
            </div>
            <h1 className="text-xl md:text-2xl font-black text-slate-900 mt-2 tracking-tight">
              Walmart USA Nationwide Store Directory & Dynamic Targeting
            </h1>
            <p className="text-xs text-slate-600 mt-1 max-w-4xl leading-relaxed">
              Target any Walmart store across all 50 US States without code changes. Click any state or store button below to instantly apply location cookies (<code className="font-mono text-sky-800">walmart.store.id</code>, <code className="font-mono text-sky-800">walmart.postalCode</code>) across the 524 dataset, live runner, and architectural audit.
            </p>
          </div>

          <div className="flex items-center gap-2 self-start lg:self-center flex-wrap">
            <button
              onClick={handleDownloadCSV}
              className="flex items-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-semibold rounded shadow-xs transition-colors cursor-pointer"
            >
              <Download className="w-3.5 h-3.5 text-sky-400" />
              <span>Export Stores CSV ({filteredStores.length})</span>
            </button>
            <button
              onClick={handleDownloadJSON}
              className="flex items-center gap-1.5 px-3 py-2 bg-[#107c41] hover:bg-[#0f6b38] text-white text-xs font-semibold rounded shadow-xs transition-colors cursor-pointer"
            >
              <Download className="w-3.5 h-3.5 text-white" />
              <span>Export Stores JSON</span>
            </button>
          </div>
        </div>

        {/* 4 Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
          <div className="bg-slate-50 p-3 rounded border border-slate-200">
            <div className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">USA State Coverage</div>
            <div className="text-xl font-black text-slate-900 mt-1">50 States + DC</div>
            <div className="text-[10.5px] text-emerald-700 font-semibold mt-0.5">56 Benchmark Stores Ready</div>
          </div>

          <div className="bg-sky-50/70 p-3 rounded border border-sky-300">
            <div className="text-[10px] text-sky-700 font-bold uppercase tracking-wider">Currently Applied Store</div>
            <div className="text-xl font-black text-[#004f98] mt-1">#{activeStore.store_number} ({activeStore.state_code})</div>
            <div className="text-[10.5px] text-slate-700 truncate mt-0.5 font-medium">{activeStore.city}, {activeStore.state} ({activeStore.zipcode})</div>
          </div>

          <div className="bg-slate-50 p-3 rounded border border-slate-200">
            <div className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Fulfillment Context</div>
            <div className="text-xl font-black text-emerald-600 mt-1">Curbside Pickup</div>
            <div className="text-[10.5px] text-slate-600 mt-0.5">Aisle-specific local shelf pricing</div>
          </div>

          <div className="bg-slate-50 p-3 rounded border border-slate-200">
            <div className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Multi-Store Execution</div>
            <div className="text-xl font-black text-purple-700 mt-1">Azure Ready</div>
            <div className="text-[10.5px] text-slate-600 mt-0.5">config.py dynamic targeting</div>
          </div>
        </div>
      </div>

      {/* PROMINENT ACTIVE TARGET APPLIED BANNER */}
      <div className="bg-gradient-to-r from-[#00386c] to-[#004f98] text-white rounded-lg p-4 md:p-5 shadow-sm border border-sky-700">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="bg-emerald-500 text-white font-bold text-[10px] px-2 py-0.5 rounded-full flex items-center gap-1 shadow-xs">
                <Check className="w-3 h-3 stroke-[3]" />
                CURRENTLY APPLIED TO SCRAPER
              </span>
              <span className="bg-sky-800 text-sky-200 font-mono text-[11px] px-2 py-0.5 rounded border border-sky-700">
                Affinity Cookie Locked
              </span>
            </div>
            <h2 className="text-lg md:text-xl font-bold flex items-center gap-2 text-white">
              <Store className="w-5 h-5 text-amber-300" />
              <span>{activeStore.name}</span>
            </h2>
            <div className="text-xs text-sky-100 flex flex-wrap items-center gap-3">
              <span className="flex items-center gap-1">
                <MapPin className="w-3.5 h-3.5 text-sky-300" />
                {activeStore.address}
              </span>
              <span>•</span>
              <span className="flex items-center gap-1">
                <Clock className="w-3.5 h-3.5 text-sky-300" />
                {activeStore.hours} ({activeStore.timezone})
              </span>
              <span>•</span>
              <span className="font-mono text-sky-200">{activeStore.phone}</span>
            </div>
            <div className="mt-2 text-[11px] font-mono bg-black/30 p-2 rounded border border-sky-800/80 text-emerald-300 break-all">
              <span className="text-sky-300 font-bold">Injected Cookie: </span>
              walmart.store.id={activeStore.store_number}; walmart.postalCode={activeStore.zipcode}; walmart.fulfillment.type=PICKUP; hasLocation=true
            </div>
          </div>

          {/* Quick-jump navigation actions to see the applied store */}
          {onNavigateTab && (
            <div className="flex flex-col sm:flex-row lg:flex-col gap-2 shrink-0">
              <button
                onClick={() => onNavigateTab('dataset')}
                className="flex items-center justify-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded shadow-xs transition-colors cursor-pointer"
              >
                <Database className="w-3.5 h-3.5" />
                <span>View 524 Dataset for #{activeStore.store_number}</span>
              </button>
              <button
                onClick={() => onNavigateTab('dashboard')}
                className="flex items-center justify-center gap-1.5 px-3 py-2 bg-white hover:bg-slate-100 text-[#00386c] text-xs font-bold rounded shadow-xs transition-colors cursor-pointer"
              >
                <Zap className="w-3.5 h-3.5 text-[#0071dc]" />
                <span>View Contest Poster</span>
              </button>
              <button
                onClick={() => onNavigateTab('runner')}
                className="flex items-center justify-center gap-1.5 px-3 py-2 bg-sky-900 hover:bg-sky-800 text-sky-100 text-xs font-semibold rounded border border-sky-700 transition-colors cursor-pointer"
              >
                <Terminal className="w-3.5 h-3.5" />
                <span>Run Playwright Scraper</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Real-time Toast Confirmation when user clicks any store */}
      {appliedFeedbackStore && (
        <div className="bg-emerald-50 border-2 border-emerald-500 rounded-lg p-3 text-emerald-950 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-md animate-in fade-in slide-in-from-top duration-200">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-emerald-600 text-white rounded-full flex items-center justify-center shrink-0">
              <Check className="w-4 h-4 stroke-[3]" />
            </div>
            <div>
              <div className="font-bold text-xs text-emerald-900">
                Store #{appliedFeedbackStore.store_number} ({appliedFeedbackStore.city}, {appliedFeedbackStore.state_code}) Applied Successfully!
              </div>
              <div className="text-[11px] text-emerald-800">
                All 524 scraped records, fulfillment cookies, and live harvester traces are now locked to {appliedFeedbackStore.name} ({appliedFeedbackStore.zipcode}).
              </div>
            </div>
          </div>
          {onNavigateTab && (
            <div className="flex items-center gap-2 self-end sm:self-center">
              <button
                onClick={() => onNavigateTab('dataset')}
                className="px-2.5 py-1 bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold rounded shadow-xs cursor-pointer"
              >
                See Dataset
              </button>
              <button
                onClick={() => onNavigateTab('dashboard')}
                className="px-2.5 py-1 bg-white hover:bg-emerald-100 text-emerald-900 border border-emerald-300 text-xs font-bold rounded shadow-xs cursor-pointer"
              >
                See Poster
              </button>
            </div>
          )}
        </div>
      )}

      {/* 2. State & Region Interactive Filter Grid */}
      <div className="bg-white rounded-lg border border-slate-300 shadow-sm p-4 md:p-5 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-3">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-sky-700" />
            <h2 className="text-sm font-bold text-slate-900">
              Select & Apply Any USA State (All 50 States + DC)
            </h2>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Auto-apply toggle */}
            <label className="flex items-center gap-1.5 text-xs text-slate-700 cursor-pointer select-none bg-slate-100 px-2 py-1 rounded border border-slate-200">
              <input
                type="checkbox"
                checked={autoApplyOnStateClick}
                onChange={(e) => setAutoApplyOnStateClick(e.target.checked)}
                className="rounded text-sky-600 focus:ring-0 cursor-pointer"
              />
              <span className="font-semibold text-[11px]">Instant 1-Click State Apply</span>
            </label>

            {/* Region Tabs */}
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded border border-slate-200 text-xs flex-wrap">
              {US_REGIONS.map((r) => (
                <button
                  key={r}
                  onClick={() => {
                    setSelectedRegion(r);
                    setSelectedStateCode('All');
                  }}
                  className={`px-2 py-0.5 rounded font-medium cursor-pointer transition-colors ${
                    selectedRegion === r ? 'bg-white shadow-xs text-sky-900 font-bold' : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {r === 'All' ? 'All (51)' : r}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* State Quick-Chips Grid (All 50 States + DC) */}
        <div>
          <div className="text-[11px] font-semibold text-slate-500 mb-1.5 flex items-center justify-between">
            <span>Click any state button below to view or instantly target:</span>
            <span className="text-[10px] text-slate-400">Green highlight indicates current active state</span>
          </div>

          <div className="flex flex-wrap gap-1.5 pt-1">
            <button
              onClick={() => setSelectedStateCode('All')}
              className={`px-2.5 py-1 rounded text-xs font-semibold cursor-pointer transition-colors ${
                selectedStateCode === 'All'
                  ? 'bg-[#004f98] text-white shadow-xs'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              }`}
            >
              All States ({ALL_USA_STORES.length} Stores)
            </button>

            {uniqueStates
              .filter((st) => selectedRegion === 'All' || st.region === selectedRegion)
              .map((st) => {
                const isStateActive = activeStore.state_code === st.code;
                const isSelectedFilter = selectedStateCode === st.code;

                return (
                  <button
                    key={st.code}
                    onClick={() => handleStateClick(st.code)}
                    className={`px-2 py-1 rounded text-xs font-mono font-medium cursor-pointer transition-all flex items-center gap-1 border ${
                      isStateActive
                        ? 'bg-emerald-600 text-white font-bold border-emerald-700 shadow-xs ring-2 ring-emerald-300'
                        : isSelectedFilter
                        ? 'bg-[#0071dc] text-white font-bold border-[#005bb5] shadow-xs'
                        : 'bg-slate-50 hover:bg-sky-50 text-slate-800 border-slate-200'
                    }`}
                    title={`${st.name} - Click to ${autoApplyOnStateClick ? 'apply store' : 'filter'}`}
                  >
                    <span>{st.code}</span>
                    {isStateActive && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                    {!isStateActive && <span className="text-[9px] opacity-75">({st.count})</span>}
                  </button>
                );
              })}
          </div>
        </div>

        {/* Selected State Fast-Action Bar */}
        {selectedStateStore && (
          <div className="mt-3 p-3 bg-sky-50 border border-sky-200 rounded-md flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-bold text-sky-900 bg-sky-200 px-2 py-0.5 rounded">
                {selectedStateStore.state_code}
              </span>
              <div>
                <span className="font-bold text-xs text-slate-900">{selectedStateStore.state}</span>
                <span className="text-xs text-slate-600 ml-1.5">
                  — Store #{selectedStateStore.store_number} ({selectedStateStore.city}, {selectedStateStore.zipcode})
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {activeStore.store_number === selectedStateStore.store_number ? (
                <span className="bg-emerald-600 text-white text-xs font-bold px-3 py-1.5 rounded flex items-center gap-1">
                  <Check className="w-3.5 h-3.5 stroke-[3]" />
                  Active Applied
                </span>
              ) : (
                <button
                  onClick={() => handleApplyStore(selectedStateStore)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-[#0071dc] hover:bg-[#005bb5] text-white text-xs font-bold rounded shadow-xs cursor-pointer transition-colors"
                >
                  <Zap className="w-3 h-3 text-amber-300" />
                  <span>Apply {selectedStateStore.state} Store Now</span>
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 3. View Switcher & Directory Table / Cards */}
      <div className="bg-white rounded-lg border border-slate-300 shadow-sm p-4 md:p-5 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-3">
          <div className="flex-1 max-w-md relative">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search by state, city, ZIP (e.g. '75001', 'Chicago', 'CA', 'Dallas')..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 border border-slate-300 rounded text-xs focus:outline-none focus:border-sky-500 font-mono"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 mr-2">
              Showing <strong className="text-slate-800">{filteredStores.length}</strong> of {ALL_USA_STORES.length} Stores
            </span>

            {/* View Mode Toggle: Table Matrix vs Cards */}
            <div className="flex items-center bg-slate-100 p-0.5 rounded border border-slate-200 text-xs">
              <button
                onClick={() => setViewFormat('matrix')}
                className={`flex items-center gap-1 px-2.5 py-1 rounded font-semibold cursor-pointer transition-colors ${
                  viewFormat === 'matrix' ? 'bg-white shadow-xs text-sky-900' : 'text-slate-600 hover:text-slate-900'
                }`}
                title="View complete 50-State coverage matrix table"
              >
                <TableIcon className="w-3.5 h-3.5 text-sky-600" />
                <span>All States Table</span>
              </button>
              <button
                onClick={() => setViewFormat('cards')}
                className={`flex items-center gap-1 px-2.5 py-1 rounded font-semibold cursor-pointer transition-colors ${
                  viewFormat === 'cards' ? 'bg-white shadow-xs text-sky-900' : 'text-slate-600 hover:text-slate-900'
                }`}
                title="View responsive store cards"
              >
                <LayoutGrid className="w-3.5 h-3.5 text-sky-600" />
                <span>Store Cards</span>
              </button>
            </div>
          </div>
        </div>

        {/* VIEW 1: ALL 50 STATES TABLE MATRIX (Direct Apply for every state) */}
        {viewFormat === 'matrix' && (
          <div className="overflow-x-auto border border-slate-200 rounded-md">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-slate-100 text-slate-700 font-bold border-b border-slate-200 uppercase text-[10px] tracking-wider">
                  <th className="py-2.5 px-3">State</th>
                  <th className="py-2.5 px-3">Store #</th>
                  <th className="py-2.5 px-3">Walmart Name</th>
                  <th className="py-2.5 px-3">City / Address</th>
                  <th className="py-2.5 px-3">ZIP</th>
                  <th className="py-2.5 px-3">Fulfillment Status</th>
                  <th className="py-2.5 px-3">Hours / Timezone</th>
                  <th className="py-2.5 px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 font-sans">
                {filteredStores.map((store) => {
                  const isCurrent = store.store_number === activeStore.store_number;

                  return (
                    <tr
                      key={store.store_number}
                      className={`transition-colors ${
                        isCurrent
                          ? 'bg-sky-50 font-medium'
                          : 'hover:bg-slate-50'
                      }`}
                    >
                      <td className="py-2 px-3 whitespace-nowrap">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-bold text-xs bg-slate-200 px-1.5 py-0.5 rounded text-slate-800">
                            {store.state_code}
                          </span>
                          <span className="text-slate-900 font-medium">{store.state}</span>
                        </div>
                      </td>

                      <td className="py-2 px-3 font-mono font-bold text-sky-800 whitespace-nowrap">
                        #{store.store_number}
                      </td>

                      <td className="py-2 px-3 font-medium text-slate-900 max-w-[200px] truncate" title={store.name}>
                        {store.name}
                      </td>

                      <td className="py-2 px-3 text-slate-600 max-w-[260px] truncate" title={store.address}>
                        <div className="flex items-center gap-1">
                          <MapPin className="w-3 h-3 text-slate-400 shrink-0" />
                          <span>{store.city}, {store.address.split(',')[0]}</span>
                        </div>
                      </td>

                      <td className="py-2 px-3 font-mono text-slate-700 whitespace-nowrap">
                        {store.zipcode}
                      </td>

                      <td className="py-2 px-3 whitespace-nowrap">
                        <span className="bg-emerald-100 text-emerald-800 text-[10px] font-bold px-2 py-0.5 rounded flex items-center gap-1 w-fit">
                          <Check className="w-3 h-3 stroke-[3]" />
                          Curbside Verified
                        </span>
                      </td>

                      <td className="py-2 px-3 text-[11px] text-slate-600 whitespace-nowrap">
                        {store.hours} ({store.timezone})
                      </td>

                      <td className="py-2 px-3 text-right whitespace-nowrap">
                        {isCurrent ? (
                          <span className="bg-emerald-600 text-white font-bold text-[11px] px-2.5 py-1 rounded inline-flex items-center gap-1 shadow-2xs">
                            <Check className="w-3 h-3 stroke-[3]" />
                            Active Applied
                          </span>
                        ) : (
                          <button
                            onClick={() => handleApplyStore(store)}
                            className="bg-[#0071dc] hover:bg-[#005bb5] text-white font-bold text-[11px] px-2.5 py-1 rounded inline-flex items-center gap-1 shadow-2xs transition-colors cursor-pointer"
                          >
                            <Zap className="w-3 h-3 text-amber-300" />
                            <span>Apply Store</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* VIEW 2: STORE CARDS GRID */}
        {viewFormat === 'cards' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {filteredStores.map((store) => {
              const isCurrent = store.store_number === activeStore.store_number;

              return (
                <div
                  key={store.store_number}
                  className={`p-3.5 rounded-lg border transition-all flex flex-col justify-between ${
                    isCurrent
                      ? 'bg-sky-50/70 border-sky-500 ring-2 ring-sky-400/40 shadow-xs'
                      : 'bg-slate-50/50 hover:bg-slate-50 border-slate-200 hover:border-slate-300 shadow-2xs'
                  }`}
                >
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-mono text-xs font-bold text-sky-800 bg-sky-100 px-1.5 py-0.2 rounded">
                            #{store.store_number}
                          </span>
                          <span className="bg-slate-200 text-slate-800 font-bold text-[10px] px-1.5 py-0.2 rounded">
                            {store.state_code}
                          </span>
                          <span className="text-[10px] text-slate-500 font-medium">
                            {store.region}
                          </span>
                        </div>
                        <h3 className="font-bold text-xs text-slate-900 mt-1 leading-snug">
                          {store.name}
                        </h3>
                      </div>

                      {isCurrent && (
                        <span className="bg-emerald-600 text-white font-bold text-[9.5px] px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0">
                          <Check className="w-3 h-3 stroke-[3]" />
                          Active
                        </span>
                      )}
                    </div>

                    {/* Address & Details */}
                    <div className="text-xs text-slate-600 space-y-1">
                      <div className="flex items-start gap-1.5">
                        <MapPin className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-0.5" />
                        <span className="text-[11px] leading-tight">{store.address}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span className="text-[11px]">{store.hours} ({store.timezone})</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Phone className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                        <span className="text-[11px] font-mono">{store.phone}</span>
                      </div>
                    </div>

                    {/* Badges */}
                    <div className="flex items-center gap-1.5 text-[10px] pt-1">
                      <span className="bg-emerald-100 text-emerald-800 px-1.5 py-0.2 rounded font-semibold flex items-center gap-0.5">
                        <Check className="w-2.5 h-2.5" />
                        Curbside Pickup
                      </span>
                      <span className="bg-sky-100 text-sky-800 px-1.5 py-0.2 rounded font-semibold">
                        In-Store Aisle Pricing
                      </span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="mt-3.5 pt-2.5 border-t border-slate-200/80 flex items-center justify-between gap-2">
                    <button
                      onClick={() => handleApplyStore(store)}
                      className={`flex-1 py-1.5 px-2.5 rounded text-xs font-semibold flex items-center justify-center gap-1.5 cursor-pointer transition-colors ${
                        isCurrent
                          ? 'bg-emerald-600 text-white shadow-xs font-bold'
                          : 'bg-[#0071dc] hover:bg-[#005bb5] text-white shadow-2xs'
                      }`}
                    >
                      <Zap className="w-3 h-3" />
                      <span>{isCurrent ? 'Active Location' : 'Target & Apply Store'}</span>
                    </button>

                    <button
                      onClick={() => copyConfigSnippet(store)}
                      className="p-1.5 bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 rounded text-xs cursor-pointer"
                      title="Copy Python StoreConfig line"
                    >
                      {copiedStoreNum === store.store_number ? (
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
