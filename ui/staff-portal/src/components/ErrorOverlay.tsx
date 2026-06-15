import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bug } from 'lucide-react';
import api from '../lib/api';

interface Stats {
  critical: number;
  high: number;
  unresolved: number;
}

export function ErrorOverlay() {
  const [stats, setStats] = useState<Stats | null>(null);
  const navigate = useNavigate();

  const poll = useCallback(async () => {
    try {
      const { data } = await api.get('/errors/stats');
      setStats({ critical: data.critical, high: data.high, unresolved: data.unresolved });
    } catch {
      setStats(null);
    }
  }, []);

  useEffect(() => {
    poll();
    const t = setInterval(poll, 30_000);
    return () => clearInterval(t);
  }, [poll]);

  const urgentCount = (stats?.critical ?? 0) + (stats?.high ?? 0);
  if (!stats || urgentCount === 0) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {/* Pulsing ring behind the button */}
      <span className="absolute inset-0 rounded-xl bg-red-500 opacity-40 animate-ping" />

      <button
        onClick={() => navigate('/errors')}
        className="relative flex items-center gap-2.5 rounded-xl px-4 py-3 shadow-2xl text-white text-sm font-semibold hover:scale-105 transition-transform focus:outline-none focus:ring-2 focus:ring-red-400 focus:ring-offset-2"
        style={{ background: 'linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)' }}
        aria-label={`${urgentCount} urgent error${urgentCount !== 1 ? 's' : ''} — click to view`}
      >
        <Bug className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{urgentCount} urgent error{urgentCount !== 1 ? 's' : ''}</span>
        <span className="flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-white/20 px-1 text-xs font-bold">
          {urgentCount}
        </span>
      </button>
    </div>
  );
}
