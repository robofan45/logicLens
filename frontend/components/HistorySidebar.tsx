'use client';

import { useState, useEffect, useCallback } from 'react';
import { History, Trash2, Clock, ChevronRight } from 'lucide-react';

interface SessionEntry {
  sessionId: string;
  timestamp: number;
  thumbnail?: string;
  summary?: string;
}

interface Props {
  onSelectSession: (sessionId: string) => void;
  currentSessionId: string | null;
}

const STORE_KEY = 'logiclens-history';

async function loadHistory(): Promise<SessionEntry[]> {
  try {
    const { get } = await import('idb-keyval');
    const stored = await get<SessionEntry[]>(STORE_KEY);
    return stored ?? [];
  } catch {
    return [];
  }
}

async function saveHistory(entries: SessionEntry[]): Promise<void> {
  try {
    const { set } = await import('idb-keyval');
    await set(STORE_KEY, entries);
  } catch {
    // idb not available
  }
}

export async function addSessionToHistory(entry: SessionEntry): Promise<void> {
  const existing = await loadHistory();
  const updated = [entry, ...existing.filter((e) => e.sessionId !== entry.sessionId)].slice(0, 50);
  await saveHistory(updated);
}

export default function HistorySidebar({ onSelectSession, currentSessionId }: Props) {
  const [entries, setEntries] = useState<SessionEntry[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadHistory().then((h) => {
      setEntries(h);
      setLoaded(true);
    });
  }, []);

  const clearHistory = useCallback(async () => {
    await saveHistory([]);
    setEntries([]);
  }, []);

  const removeEntry = useCallback(
    async (sessionId: string) => {
      const updated = entries.filter((e) => e.sessionId !== sessionId);
      setEntries(updated);
      await saveHistory(updated);
    },
    [entries],
  );

  return (
    <aside className="flex h-screen w-72 shrink-0 flex-col border-r border-gray-800 bg-gray-900">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <History size={15} className="text-gray-400" />
          <span className="text-sm font-semibold text-gray-300">Session History</span>
        </div>
        {entries.length > 0 && (
          <button
            onClick={clearHistory}
            title="Clear history"
            className="rounded p-1 text-gray-600 hover:text-red-400"
          >
            <Trash2 size={13} />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {!loaded ? (
          <p className="p-4 text-xs text-gray-600">Loading…</p>
        ) : entries.length === 0 ? (
          <div className="p-4 text-center">
            <History size={24} className="mx-auto mb-2 text-gray-700" />
            <p className="text-xs text-gray-600">No past sessions</p>
          </div>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.sessionId}
              className={`group flex cursor-pointer items-start gap-3 border-b border-gray-800 px-4 py-3 hover:bg-gray-800 ${
                entry.sessionId === currentSessionId ? 'bg-blue-950/30' : ''
              }`}
              onClick={() => onSelectSession(entry.sessionId)}
            >
              {/* Thumbnail */}
              {entry.thumbnail ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={entry.thumbnail}
                  alt=""
                  className="h-10 w-14 shrink-0 rounded object-cover"
                />
              ) : (
                <div className="flex h-10 w-14 shrink-0 items-center justify-center rounded bg-gray-800">
                  <History size={16} className="text-gray-600" />
                </div>
              )}

              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-xs text-gray-300">
                  {entry.sessionId.slice(0, 16)}…
                </p>
                <p className="mt-0.5 flex items-center gap-1 text-xs text-gray-600">
                  <Clock size={10} />
                  {new Date(entry.timestamp).toLocaleString()}
                </p>
                {entry.summary && (
                  <p className="mt-0.5 truncate text-xs text-gray-500">{entry.summary}</p>
                )}
              </div>

              <div className="flex shrink-0 flex-col gap-1">
                <ChevronRight size={12} className="text-gray-600 group-hover:text-gray-400" />
                <button
                  onClick={(e) => { e.stopPropagation(); removeEntry(entry.sessionId); }}
                  className="rounded p-0.5 text-gray-700 hover:text-red-400"
                  title="Remove"
                >
                  <Trash2 size={10} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
