import React from 'react';

export function WalmartSpark({ className = "w-6 h-6" }: { className?: string }) {
  // Walmart 6-petal sunburst spark in yellow #FFC220
  return (
    <svg viewBox="0 0 100 100" fill="currentColor" className={`text-[#FFC220] ${className}`}>
      {/* 6 radiating capsules rotated at 0, 60, 120, 180, 240, 300 degrees */}
      {[0, 60, 120, 180, 240, 300].map((angle, i) => (
        <g key={i} transform={`rotate(${angle} 50 50)`}>
          <rect x="44" y="6" width="12" height="28" rx="6" fill="#FFC220" />
        </g>
      ))}
    </svg>
  );
}

export function WalmartLogo({ className = "h-8" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      <span className="font-bold text-white text-2xl tracking-tight font-sans">Walmart</span>
      <WalmartSpark className="w-6 h-6 mb-0.5" />
    </div>
  );
}

export function AzureLogo({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 96 96" className={className} fill="none">
      <path
        d="M26.2 84.5h43.6c2.8 0 4.6-2.9 3.3-5.3L49.9 35.7a3.8 3.8 0 00-6.6 0L22.9 79.2c-1.3 2.4.5 5.3 3.3 5.3z"
        fill="url(#azure_grad_1)"
      />
      <path
        d="M57.6 15.6l-18 34.6 16.5 28.5c1.4 2.4 4.8 2.3 6.1-.2L79 43.1a3.8 3.8 0 00-3.3-5.4H57.6z"
        fill="url(#azure_grad_2)"
        opacity="0.9"
      />
      <defs>
        <linearGradient id="azure_grad_1" x1="22" y1="84" x2="68" y2="35" gradientUnits="userSpaceOnUse">
          <stop stopColor="#114A8B" />
          <stop offset="1" stopColor="#0078D4" />
        </linearGradient>
        <linearGradient id="azure_grad_2" x1="45" y1="18" x2="80" y2="78" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0078D4" />
          <stop offset="0.5" stopColor="#50E6FF" />
          <stop offset="1" stopColor="#0078D4" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export function PlaywrightLogo({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} fill="none">
      {/* Green theatre masks logo */}
      <circle cx="50" cy="50" r="46" fill="#15803d" />
      {/* Mask 1 */}
      <path
        d="M32 26c-9 0-16 8-16 18 0 16 11 26 16 29 5-3 16-13 16-29 0-10-7-18-16-18z"
        fill="#22c55e"
      />
      <ellipse cx="26" cy="40" rx="3.5" ry="4.5" fill="#14532d" />
      <ellipse cx="38" cy="40" rx="3.5" ry="4.5" fill="#14532d" />
      <path d="M26 53 Q32 60 38 53" stroke="#14532d" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      {/* Mask 2 overlay */}
      <path
        d="M66 34c-8 0-14 7-14 16 0 14 10 23 14 26 4-3 14-12 14-26 0-9-6-16-14-16z"
        fill="#4ade80"
      />
      <ellipse cx="61" cy="46" rx="3" ry="4" fill="#166534" />
      <ellipse cx="71" cy="46" rx="3" ry="4" fill="#166534" />
      <path d="M61 58 Q66 52 71 58" stroke="#166534" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export function PythonLogo({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 128 128" className={className}>
      <path
        d="M63.7 3.5c-29.3 0-27.5 12.7-27.5 12.7l.1 13.2h28.1v4H24.8C9.5 33.4 9 45.4 9 45.4s-.5 13.9 0 21.2c.6 9 8.2 8.7 8.2 8.7h5.1V64.8c0-8.9 7.7-8.6 7.7-8.6h28.1c7.4 0 7.2-7.1 7.2-7.1V24.5c0-8.1-11.6-21-0-21zm-13.4 8.7a3.8 3.8 0 110 7.6 3.8 3.8 0 010-7.6z"
        fill="#3776AB"
      />
      <path
        d="M64.3 124.5c29.3 0 27.5-12.7 27.5-12.7l-.1-13.2H63.6v-4h39.6c15.3 0 15.8-12 15.8-12s.5-13.9 0-21.2c-.6-9-8.2-8.7-8.2-8.7h-5.1v10.5c0 8.9-7.7 8.6-7.7 8.6H49.9c-7.4 0-7.2 7.1-7.2 7.1v24.6c0 8.1 11.6 21 0 21zm13.4-8.7a3.8 3.8 0 110-7.6 3.8 3.8 0 010 7.6z"
        fill="#FFD43B"
      />
    </svg>
  );
}

export function AzureStorageLogo({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} fill="none">
      <rect x="8" y="10" width="48" height="12" rx="4" fill="#0078D4" />
      <rect x="8" y="26" width="48" height="12" rx="4" fill="#0078D4" />
      <rect x="8" y="42" width="48" height="12" rx="4" fill="#0078D4" />
      <circle cx="16" cy="16" r="2" fill="#50E6FF" />
      <circle cx="16" cy="32" r="2" fill="#50E6FF" />
      <circle cx="16" cy="48" r="2" fill="#50E6FF" />
    </svg>
  );
}

export function ProxiesLogo({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} fill="none">
      <circle cx="32" cy="32" r="26" stroke="#0078D4" strokeWidth="4" />
      <ellipse cx="32" cy="32" rx="14" ry="26" stroke="#0078D4" strokeWidth="4" />
      <line x1="6" y1="32" x2="58" y2="32" stroke="#0078D4" strokeWidth="4" />
      <line x1="12" y1="20" x2="52" y2="20" stroke="#0078D4" strokeWidth="3" />
      <line x1="12" y1="44" x2="52" y2="44" stroke="#0078D4" strokeWidth="3" />
    </svg>
  );
}

export function KeyVaultLogo({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} fill="none">
      <path
        d="M32 6L10 16v18c0 14.5 9.4 28 22 32 12.6-4 22-17.5 22-32V16L32 6z"
        fill="#0078D4"
      />
      <circle cx="32" cy="28" r="7" fill="#ffffff" />
      <path d="M34 40h4v4h-4z" fill="#ffffff" />
      <path d="M34 46h4v4h-4z" fill="#ffffff" />
    </svg>
  );
}

export function ChecklistDocument({ className = "w-5 h-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none">
      <rect x="3" y="3" width="18" height="18" rx="3" fill="#0284c7" />
      <line x1="7" y1="8" x2="17" y2="8" stroke="white" strokeWidth="2" strokeLinecap="round" />
      <line x1="7" y1="12" x2="17" y2="12" stroke="white" strokeWidth="2" strokeLinecap="round" />
      <line x1="7" y1="16" x2="13" y2="16" stroke="white" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

