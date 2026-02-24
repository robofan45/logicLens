'use client';

import type { ParsedElement } from '@/lib/api';

interface Props {
  elements: ParsedElement[];
  totalRungs: number;
}

// Render a single element as ASCII-art styled badge
function ElementBadge({ element }: { element: ParsedElement }) {
  const type = element.element_type?.toLowerCase() ?? '';

  if (type.includes('coil') || type.includes('output')) {
    return (
      <span className="mx-1 inline-flex items-center gap-0.5 font-mono text-sm">
        <span className="text-gray-600">&#x2500;</span>
        <span className="rounded border border-orange-500 px-1 text-orange-400">
          ({element.address || element.label || 'O'})
        </span>
        <span className="text-gray-600">&#x2500;</span>
      </span>
    );
  }

  if (type.includes('timer')) {
    return (
      <span className="mx-1 inline-flex items-center gap-0.5 font-mono text-sm">
        <span className="text-gray-600">&#x2500;</span>
        <span className="rounded border border-green-500 px-1 text-green-400">
          [T:{element.address || element.label}]
        </span>
        <span className="text-gray-600">&#x2500;</span>
      </span>
    );
  }

  if (type.includes('counter')) {
    return (
      <span className="mx-1 inline-flex items-center gap-0.5 font-mono text-sm">
        <span className="text-gray-600">&#x2500;</span>
        <span className="rounded border border-purple-500 px-1 text-purple-400">
          [C:{element.address || element.label}]
        </span>
        <span className="text-gray-600">&#x2500;</span>
      </span>
    );
  }

  // Default: contact / input
  return (
    <span className="mx-1 inline-flex items-center gap-0.5 font-mono text-sm">
      <span className="text-gray-600">&#x2500;</span>
      <span className="text-gray-400">|</span>
      <span className="rounded border border-blue-500 px-1 text-blue-400">
        {element.address || element.label || '?'}
      </span>
      <span className="text-gray-400">|</span>
      <span className="text-gray-600">&#x2500;</span>
    </span>
  );
}

export default function LadderDiagramView({ elements, totalRungs }: Props) {
  if (elements.length === 0) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-500">
          Ladder Diagram
        </h3>
        <p className="text-sm text-gray-600">No elements to display.</p>
      </div>
    );
  }

  // Group elements by rung
  const byRung: Record<number, ParsedElement[]> = {};
  for (let r = 0; r < totalRungs; r++) byRung[r] = [];
  elements.forEach((el) => {
    const rung = el.rung ?? 0;
    if (!byRung[rung]) byRung[rung] = [];
    byRung[rung].push(el);
  });

  // Sort elements in each rung by x position
  Object.values(byRung).forEach((arr) =>
    arr.sort((a, b) => (a.position_x ?? 0) - (b.position_x ?? 0)),
  );

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
          Ladder Diagram
        </h3>
        <span className="text-xs text-gray-600">{totalRungs} rungs · {elements.length} elements</span>
      </div>

      {/* Legend */}
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        <span className="flex items-center gap-1">
          <span className="rounded border border-blue-500 px-1 text-blue-400 font-mono">|X|</span>
          <span className="text-gray-500">Contact/Input</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="rounded border border-orange-500 px-1 text-orange-400 font-mono">(O)</span>
          <span className="text-gray-500">Coil/Output</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="rounded border border-green-500 px-1 text-green-400 font-mono">[T]</span>
          <span className="text-gray-500">Timer</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="rounded border border-purple-500 px-1 text-purple-400 font-mono">[C]</span>
          <span className="text-gray-500">Counter</span>
        </span>
      </div>

      <div className="max-h-96 overflow-y-auto space-y-1 rounded-lg bg-gray-950 p-3">
        {Object.entries(byRung).map(([rungStr, rungElements]) => {
          const rung = Number(rungStr);
          return (
            <div key={rung} className="flex items-center">
              {/* Rail and rung number */}
              <span className="mr-2 w-16 shrink-0 text-right font-mono text-xs text-gray-600">
                Rung {rung + 1}
              </span>
              <span className="font-mono text-gray-700 text-sm">&#x2551;</span>
              {rungElements.length === 0 ? (
                <span className="mx-2 font-mono text-xs text-gray-700 italic">empty</span>
              ) : (
                rungElements.map((el) => (
                  <ElementBadge key={el.id} element={el} />
                ))
              )}
              <span className="ml-auto font-mono text-gray-700 text-sm">&#x2551;</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
