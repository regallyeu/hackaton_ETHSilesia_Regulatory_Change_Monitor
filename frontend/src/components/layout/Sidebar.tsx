import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export function Sidebar() {
  const { t, i18n } = useTranslation()

  const navItems = [
    { to: '/', label: t('common:nav.dashboard'), icon: '⬛' },
    { to: '/alerts', label: t('common:nav.alerts'), icon: '🔔' },
    { to: '/isap', label: t('common:nav.isap'), icon: '📚' },
    { to: '/signed-documents', label: t('common:nav.signedDocuments'), icon: '✅' },
  ]

  return (
    <aside className="w-60 min-h-screen bg-slate-900 text-slate-100 flex flex-col shrink-0">
      <div className="px-6 py-5 border-b border-slate-700">
        <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-1">Regulatory</div>
        <div className="text-base font-bold text-white leading-tight">Change Monitor</div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {navItems.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
              }`
            }
          >
            <span className="text-base">{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-4 py-4 border-t border-slate-700 space-y-3">
        <div className="flex items-center gap-1">
          {(['pl', 'en'] as const).map((lang) => (
            <button
              key={lang}
              onClick={() => i18n.changeLanguage(lang)}
              className={`px-2 py-1 text-xs rounded font-medium transition-colors ${
                i18n.language === lang
                  ? 'bg-slate-100 text-slate-900'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
              }`}
            >
              {lang.toUpperCase()}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-xs text-slate-400">{t('common:monitoring.active')}</span>
        </div>
      </div>
    </aside>
  )
}
