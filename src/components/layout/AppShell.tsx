import type { ReactNode } from 'react'

export type Page = 'new' | 'jobs' | 'outputs' | 'settings'

const navItems: { id: Page; label: string; icon: string }[] = [
  { id: 'new', label: 'Video mới', icon: '+' },
  { id: 'jobs', label: 'Công việc', icon: '□' },
  { id: 'outputs', label: 'Đầu ra', icon: '□' },
  { id: 'settings', label: 'Cài đặt', icon: '□' },
]

const pageTitles: Record<Page, string> = {
  new: 'Tạo video',
  jobs: 'Công việc',
  outputs: 'Video Đầu ra',
  settings: 'Cài đặt',
}

export function AppShell({ page, onPageChange, busy, degraded, onLogout, userName, isAdmin, children }: {
  page: Page
  onPageChange: (page: Page) => void
  busy: boolean
  degraded: boolean
  onLogout: () => void
  userName: string
  isAdmin: boolean
  children: ReactNode
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Điều hướng chính">
        <div className="brand-mark" aria-label="Video Production Pipeline">VP</div>
        <nav>
          {navItems.map((item) => (
            <button
              className={'nav-item ' + (page === item.id ? 'active' : '')}
              key={item.id}
              onClick={() => onPageChange(item.id)}
              aria-current={page === item.id ? 'page' : undefined}
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.id === 'jobs' ? (isAdmin ? 'Tất cả công việc' : 'Công việc của tôi') : item.label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-version">v0.2 LAN</div>
      </aside>

      <div className="app-frame">
        <header className="topbar">
          <div>
            <span className="eyebrow">Video Production Pipeline</span>
            <h1>{pageTitles[page]}</h1>
          </div>
          <div className="topbar-actions">
            <span className="current-user">{userName}{isAdmin ? ' · Admin' : ''}</span>
            <div className={'system-status ' + (busy || degraded ? 'busy' : '')} role="status">
              <span className="status-dot" />
              {degraded ? 'Hệ thống chưa sẵn sàng' : busy ? 'Đang xử lý' : 'Hệ thống sẵn sàng'}
            </div>
            <button className="ghost-button" onClick={onLogout}>Đăng xuất</button>
          </div>
        </header>
        <main>{children}</main>
      </div>
    </div>
  )
}
