import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import {
  LayoutDashboard, FileText, FilePlus, AlertTriangle,
  MessageSquare, BarChart3, Receipt, Settings, LogOut,
  Bell, TrendingUp, ChevronLeft, ChevronRight,
  Activity, Search,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

const NAV = [
  { to: '/dashboard',  label: 'Dashboard',  icon: LayoutDashboard, group: 'Revenue Cycle' },
  { to: '/claims',     label: 'My Claims',  icon: FileText,         group: 'Revenue Cycle' },
  { to: '/charges',    label: 'Charges',    icon: FilePlus,         group: 'Revenue Cycle' },
  { to: '/denials',    label: 'Denials',    icon: AlertTriangle,    group: 'Revenue Cycle' },
  { to: '/analytics',  label: 'Analytics',  icon: TrendingUp,       group: 'Insights' },
  { to: '/reports',    label: 'Reports',    icon: BarChart3,        group: 'Insights' },
  { to: '/messages',   label: 'Messages',   icon: MessageSquare,    group: 'Communications' },
  { to: '/invoices',   label: 'Invoices',   icon: Receipt,          group: 'Communications' },
  { to: '/settings',   label: 'Settings',   icon: Settings,         group: '' },
];

const GROUPS = ['Revenue Cycle', 'Insights', 'Communications', ''];

function initials(name?: string) {
  if (!name) return 'DR';
  return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
}

export function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-primary)' }}>

      {/* ── SIDEBAR ─────────────────────────────────────────── */}
      <aside
        className="flex flex-col flex-shrink-0 transition-all duration-200 relative z-20"
        style={{
          width: collapsed ? '64px' : '220px',
          background: 'var(--bg-sidebar)',
          borderRight: '1px solid var(--border)',
        }}
      >
        {/* Logo row */}
        <div
          className="flex items-center gap-3 px-4 h-14 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <svg width="32" height="32" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" className="flex-shrink-0">
            <defs>
              <linearGradient id="providerMark" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#003087"/>
                <stop offset="100%" stopColor="#0066cc"/>
              </linearGradient>
            </defs>
            <rect width="100" height="100" rx="22" fill="url(#providerMark)"/>
            <path fillRule="evenodd"
              d="M 50 10 L 87 90 L 75 90 L 65 64 L 35 64 L 25 90 L 13 90 Z M 50 24 L 62 58 L 38 58 Z"
              fill="white"/>
          </svg>
          {!collapsed && (
            <div className="overflow-hidden">
              <p className="text-sm font-bold leading-tight truncate" style={{ color: 'var(--text-primary)' }}>Aethera Healthcare</p>
              <p className="text-[10px] truncate" style={{ color: 'var(--text-subtle)' }}>Provider Portal</p>
            </div>
          )}
        </div>

        {/* Nav groups */}
        <nav className="flex-1 overflow-y-auto py-3 px-2" style={{ scrollbarWidth: 'none' }}>
          {GROUPS.map(group => {
            const items = NAV.filter(n => n.group === group);
            if (!items.length) return null;
            return (
              <div key={group} className="mb-2">
                {!collapsed && group && (
                  <p className="px-3 py-1 text-[9px] font-bold uppercase tracking-widest" style={{ color: 'var(--text-subtle)' }}>
                    {group}
                  </p>
                )}
                {collapsed && group && (
                  <div className="my-2 mx-3 h-px" style={{ background: 'var(--border)' }} />
                )}
                <ul className="space-y-0.5">
                  {items.map(({ to, label, icon: Icon }) => (
                    <li key={to}>
                      <NavLink to={to} title={collapsed ? label : undefined}>
                        {({ isActive }) => (
                          <div
                            className={['flex items-center gap-3 rounded-lg px-3 py-2 text-xs font-medium cursor-pointer border-l-2 transition-colors duration-100', collapsed ? 'justify-center px-2' : ''].join(' ')}
                            style={{
                              background: isActive ? 'var(--sidebar-active-bg)' : 'transparent',
                              color: isActive ? 'var(--sidebar-text-active)' : 'var(--sidebar-text)',
                              borderLeftColor: isActive ? '#003087' : 'transparent',
                            }}
                          >
                            <Icon className="h-4 w-4 flex-shrink-0" />
                            {!collapsed && <span>{label}</span>}
                          </div>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>

        {/* User + collapse */}
        <div className="flex-shrink-0" style={{ borderTop: '1px solid var(--border)' }}>
          <div className={['flex items-center gap-2.5 px-3 py-3', collapsed ? 'justify-center' : ''].join(' ')}>
            <div
              className="h-7 w-7 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold text-white"
              style={{ background: 'linear-gradient(135deg, #003087, #0066cc)' }}
            >
              {initials(user?.full_name)}
            </div>
            {!collapsed && (
              <div className="overflow-hidden flex-1 min-w-0">
                <p className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{user?.full_name ?? 'Provider'}</p>
                <p className="text-[10px] truncate" style={{ color: 'var(--text-subtle)' }}>{(user as any)?.practice_name ?? 'Practice'}</p>
              </div>
            )}
            {!collapsed && (
              <button
                onClick={() => { logout(); navigate('/login'); }}
                className="rounded-lg p-1.5 flex-shrink-0 transition-colors"
                style={{ color: 'var(--text-subtle)' }}
                onMouseEnter={e => { e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.background = 'rgba(239,68,68,0.08)'; }}
                onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-subtle)'; e.currentTarget.style.background = 'transparent'; }}
                title="Sign out"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <div className="px-2 pb-2">
            <button
              onClick={() => setCollapsed(c => !c)}
              className="w-full flex items-center justify-center rounded-lg py-1.5 text-xs transition-colors"
              style={{ color: 'var(--text-subtle)' }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-tertiary)'; e.currentTarget.style.color = 'var(--text-muted)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-subtle)'; }}
            >
              {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>
      </aside>

      {/* ── MAIN ────────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Top bar */}
        <header
          className="flex h-14 items-center justify-between px-6 flex-shrink-0"
          style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}
        >
          {/* Search */}
          <div
            className="flex items-center gap-2 rounded-lg px-3 py-1.5 flex-1 max-w-xs"
            style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)' }}
          >
            <Search className="h-3.5 w-3.5 flex-shrink-0" style={{ color: 'var(--text-subtle)' }} />
            <input
              className="flex-1 bg-transparent text-xs outline-none"
              placeholder="Search claims, patients..."
              style={{ color: 'var(--text-primary)' }}
            />
            <kbd className="text-[10px] px-1.5 py-0.5 rounded hidden sm:block" style={{ background: 'var(--border)', color: 'var(--text-subtle)' }}>K</kbd>
          </div>

          <div className="flex items-center gap-2 ml-4">
            {/* Live badge */}
            <div
              className="hidden md:flex items-center gap-1.5 rounded-full px-3 py-1"
              style={{ background: 'rgba(5,150,105,0.07)', border: '1px solid rgba(5,150,105,0.15)' }}
            >
              <Activity className="h-3 w-3 text-emerald-500" />
              <span className="text-[10px] font-medium text-emerald-600">Live</span>
            </div>

            <button
              className="relative rounded-lg p-2 transition-colors"
              style={{ color: 'var(--text-muted)' }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-tertiary)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              <Bell className="h-4 w-4" />
              <span className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-[#003087]" />
            </button>

            <div className="h-6 w-px mx-1" style={{ background: 'var(--border)' }} />

            <div className="flex items-center gap-2.5">
              <div
                className="h-7 w-7 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #003087, #0066cc)' }}
              >
                {initials(user?.full_name)}
              </div>
              <div className="hidden md:block">
                <p className="text-xs font-semibold leading-tight" style={{ color: 'var(--text-primary)' }}>{user?.full_name ?? 'Provider'}</p>
                <p className="text-[10px] leading-tight" style={{ color: 'var(--text-subtle)' }}>{(user as any)?.practice_name ?? 'Practice'}</p>
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
