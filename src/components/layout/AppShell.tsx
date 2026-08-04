import type { ReactNode } from 'react'

export type Page = 'new' | 'jobs' | 'outputs' | 'settings'

const navItems: { id: Page; label: string; icon: string }[] = [
  { id: 'new', label: 'Video mới', icon: '+' },
  { id: 'jobs', label: 'Công việc', icon: '≡' },
  { id: 'outputs', label: 'Đầu ra', icon: '□' },
  { id: 'settings', label: 'Cài đặt', icon: '⚙' },
]

const pageTitles: Record<Page, string> = {
  new: 'Tạo video',
  jobs: 'Công việc',
  outputs: 'Video đầu ra',
  settings: 'Cài đặt',
}

export function AppShell({ page, onPageChange, busy, children }: {
  page: Page
  onPageChange: (page: Page) => void
  busy: boolean
  children: ReactNode
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Điều hướng chính">
        <div className="brand-mark" aria-label="Video Production Pipeline">VP</div>
        <nav>
          {navItems.map((item) => (
            <button
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              key={item.id}
              onClick={() => onPageChange(item.id)}
              aria-current={page === item.id ? 'page' : undefined}
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-version">v0.1 mock</div>
      </aside>

      <div className="app-frame">
        <header className="topbar">
          <div>
            <span className="eyebrow">Video Production Pipeline</span>
            <h1>{pageTitles[page]}</h1>
          </div>
          <div className="topbar-actions">
            <div className={`system-status ${busy ? 'busy' : ''}`} role="status">
              <span className="status-dot" />
              {busy ? 'Đang xử lý' : 'Hệ thống sẵn sàng'}
            </div>
            <button className="icon-button" aria-label="Mở cài đặt" onClick={() => onPageChange('settings')}>⚙</button>
          </div>
        </header>
        <main>{children}</main>
      </div>
    </div>
  )
}
