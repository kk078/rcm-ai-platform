import { useState, useRef, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Sun, Moon, Bell, Search, ChevronDown, LogOut, User } from 'lucide-react';
import { useTheme } from './ThemeProvider';
import { useAuth } from '../hooks/useAuth';

const ROUTE_TITLES: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/queues':    'Work Queues',
  '/claims':    'Claims',
  '/coding':    'Coding',
  '/payments':  'Payments',
  '/denials':   'Denials',
  '/clients':   'Clients',
  '/billing':   'Billing',
  '/settings':  'Settings',
};

function getInitials(name: string): string {
  return name
    .split(' ')
    .map((n) => n[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

export function Topbar() {
  const { toggleTheme, isDark } = useTheme();
  const { user, logout } = useAuth();
  const location = useLocation();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const pageTitle = ROUTE_TITLES[location.pathname] ?? 'Aethera AI';
  const initials = user?.full_name ? getInitials(user.full_name) : '?';

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header
      className="flex h-14 items-center gap-4 border-b px-6"
      style={{
        backgroundColor: 'var(--bg-secondary)',
        borderColor: 'var(--border)',
      }}
    >
      {/* Page title */}
      <h2
        className="text-base font-semibold mr-4 hidden sm:block"
        style={{ color: 'var(--text-primary)' }}
      >
        {pageTitle}
      </h2>

      {/* Search bar */}
      <div className="flex-1 max-w-md">
        <div
          className="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm"
          style={{
            backgroundColor: 'var(--bg-primary)',
            borderColor: 'var(--border)',
            color: 'var(--text-subtle)',
          }}
        >
          <Search className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--text-subtle)' }} />
          <input
            type="text"
            placeholder="Search patients, claims, codes..."
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-[var(--text-subtle)]"
            style={{ color: 'var(--text-primary)' }}
          />
          <kbd
            className="hidden sm:inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium"
            style={{ borderColor: 'var(--border)', color: 'var(--text-subtle)' }}
          >
            ⌘K
          </kbd>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          className="flex h-8 w-8 items-center justify-center rounded-lg transition-colors hover:bg-[var(--bg-tertiary)]"
          style={{ color: 'var(--text-muted)' }}
        >
          {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        {/* Notifications */}
        <button
          title="Notifications"
          className="relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors hover:bg-[var(--bg-tertiary)]"
          style={{ color: 'var(--text-muted)' }}
        >
          <Bell className="h-4 w-4" />
          <span className="absolute top-1 right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-aethera-600 text-[9px] font-bold text-white">
            3
          </span>
        </button>

        {/* User dropdown */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen((o) => !o)}
            className="flex items-center gap-2 rounded-lg px-2 py-1 transition-colors hover:bg-[var(--bg-tertiary)]"
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-aethera-500 to-violet-600 text-xs font-bold text-white">
              {initials}
            </div>
            <span
              className="hidden sm:block text-sm font-medium"
              style={{ color: 'var(--text-primary)' }}
            >
              {user?.full_name?.split(' ')[0] ?? 'User'}
            </span>
            <ChevronDown
              className="h-3.5 w-3.5 hidden sm:block"
              style={{ color: 'var(--text-subtle)' }}
            />
          </button>

          {dropdownOpen && (
            <div
              className="absolute right-0 top-full mt-2 w-56 rounded-xl border shadow-lg z-50 animate-slide-in py-1"
              style={{
                backgroundColor: 'var(--card-bg)',
                borderColor: 'var(--border)',
                boxShadow: 'var(--shadow-lg)',
              }}
            >
              {/* User info header */}
              <div
                className="px-4 py-3 border-b"
                style={{ borderColor: 'var(--border)' }}
              >
                <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                  {user?.full_name}
                </p>
                <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  {user?.email}
                </p>
                {user?.internal_role && (
                  <span className="mt-1.5 inline-flex items-center rounded-md bg-aethera-600/10 px-2 py-0.5 text-[10px] font-medium text-aethera-600 dark:text-aethera-400">
                    {user.internal_role}
                  </span>
                )}
              </div>

              {/* Profile link */}
              <button
                onClick={() => setDropdownOpen(false)}
                className="flex w-full items-center gap-2.5 px-4 py-2 text-sm transition-colors hover:bg-[var(--bg-tertiary)]"
                style={{ color: 'var(--text-primary)' }}
              >
                <User className="h-4 w-4" style={{ color: 'var(--text-muted)' }} />
                Profile
              </button>

              {/* Sign out */}
              <button
                onClick={() => { setDropdownOpen(false); logout(); }}
                className="flex w-full items-center gap-2.5 px-4 py-2 text-sm transition-colors hover:bg-red-50 dark:hover:bg-red-900/20 text-red-600 dark:text-red-400"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
