import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, ListTodo, FileText, Code2, CreditCard,
  AlertTriangle, Building2, Receipt, Settings, LogOut,
  ChevronLeft, ChevronRight, Sparkles, ShieldCheck, ShieldAlert,
  UserRound, FolderOpen, Plug, Bug, KeyRound, Activity,
  UsersRound, BookOpen,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

interface NavItem { to: string; label: string; icon: React.ElementType; adminOnly?: boolean; }

const coreItems: NavItem[] = [
  { to: '/dashboard',       label: 'Dashboard',      icon: LayoutDashboard },
  { to: '/queues',          label: 'Work Queues',     icon: ListTodo },
  { to: '/claims',          label: 'Claims',          icon: FileText },
  { to: '/coding',          label: 'Coding',          icon: Code2 },
  { to: '/payments',        label: 'Payments',        icon: CreditCard },
  { to: '/denials',         label: 'Denials',         icon: AlertTriangle },
  { to: '/eligibility',     label: 'Eligibility',     icon: ShieldCheck },
  { to: '/prior-auth',      label: 'Prior Auth',      icon: ShieldAlert },
  { to: '/patient-billing', label: 'Patient Billing', icon: UserRound },
  { to: '/documents',       label: 'Documents',       icon: FolderOpen },
  { to: '/ai-assistant',    label: 'AI Assistant',    icon: Sparkles },
];

const mgmtItems: NavItem[] = [
  { to: '/clients',             label: 'Clients',            icon: Building2 },
  { to: '/billing',             label: 'Billing',            icon: Receipt },
  { to: '/provider-logins',     label: 'Provider Logins',    icon: KeyRound,  adminOnly: true },
  { to: '/ehr-connections',     label: 'EHR / PMS',          icon: Plug,      adminOnly: true },
  { to: '/agent-monitor',       label: 'AI Agents',          icon: Activity,  adminOnly: true },
  { to: '/error-intelligence',  label: 'Error Intelligence', icon: Bug,       adminOnly: true },
  { to: '/users',               label: 'User Management',    icon: UsersRound, adminOnly: true },
  { to: '/references',          label: 'References',          icon: BookOpen,  adminOnly: true },
  { to: '/settings',            label: 'Settings',           icon: Settings },
];

function getInitials(name: string) {
  return name.split(' ').map((n) => n[0]).slice(0, 2).join('').toUpperCase();
}

export function Sidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const initials = user?.full_name ? getInitials(user.full_name) : '?';
  const isAdmin = user?.internal_role === 'company_admin' || user?.internal_role === 'admin';

  function NavSection({ label, items }: { label: string; items: NavItem[] }) {
    const visibleItems = items.filter((item) => !item.adminOnly || isAdmin);
    if (visibleItems.length === 0) return null;
    return (
      <div className="mb-4">
        {!collapsed && (
          <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'var(--text-subtle)' }}>
            {label}
          </p>
        )}
        <ul className="space-y-0.5">
          {visibleItems.map(({ to, label: lbl, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                title={collapsed ? lbl : undefined}
                className={({ isActive }) =>
                  ['flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors border-l-2',
                   collapsed ? 'justify-center' : '',
                   isActive ? 'bg-aethera-600/10 text-aethera-600 border-aethera-600' : 'border-transparent hover:bg-[var(--bg-tertiary)]',
                  ].join(' ')
                }
                style={({ isActive }) => ({ color: isActive ? undefined : 'var(--text-muted)' })}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && <span>{lbl}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <aside
      className={['flex flex-col border-r transition-all duration-200 shrink-0', collapsed ? 'w-14' : 'w-56'].join(' ')}
      style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border)' }}
    >
      <div className="flex items-center gap-3 px-3 h-14 border-b shrink-0" style={{ borderColor: 'var(--border)' }}>
        <svg width="32" height="32" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" className="shrink-0">
          <defs>
            <linearGradient id="sidebarMark" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#003087"/>
              <stop offset="100%" stopColor="#0066cc"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" rx="22" fill="url(#sidebarMark)"/>
          <path fillRule="evenodd"
            d="M 50 10 L 87 90 L 75 90 L 65 64 L 35 64 L 25 90 L 13 90 Z M 50 24 L 62 58 L 38 58 Z"
            fill="white"/>
        </svg>
        {!collapsed && (
          <div className="overflow-hidden">
            <p className="text-sm font-bold truncate" style={{ color: 'var(--text-primary)' }}>Aethera AI</p>
            <p className="text-[10px] truncate" style={{ color: 'var(--text-subtle)' }}>Staff Portal</p>
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto py-3 px-2">
        <NavSection label="Core RCM" items={coreItems} />
        <NavSection label="Management" items={mgmtItems} />
      </nav>

      <div className="border-t px-2 py-3 space-y-1 shrink-0" style={{ borderColor: 'var(--border)' }}>
        <div className={['flex items-center gap-2.5 rounded-lg px-2 py-2', collapsed ? 'justify-center' : ''].join(' ')}>
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-aethera-600/20 text-xs font-bold text-aethera-600">
            {initials}
          </div>
          {!collapsed && (
            <div className="overflow-hidden flex-1">
              <p className="text-xs font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{user?.full_name ?? 'User'}</p>
              <p className="text-[10px] truncate" style={{ color: 'var(--text-subtle)' }}>{user?.email ?? ''}</p>
            </div>
          )}
        </div>
        <button
          onClick={() => { logout(); navigate('/login'); }}
          className={['flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-xs font-medium transition-colors hover:bg-red-50 hover:text-red-600', collapsed ? 'justify-center' : ''].join(' ')}
          style={{ color: 'var(--text-muted)' }}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex w-full items-center justify-center rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-[var(--bg-tertiary)]"
          style={{ color: 'var(--text-subtle)' }}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  );
}
