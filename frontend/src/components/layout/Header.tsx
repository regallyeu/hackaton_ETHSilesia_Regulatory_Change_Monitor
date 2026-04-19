import { useTranslation } from 'react-i18next'

export function Header() {
  const { i18n } = useTranslation()
  return (
    <header className="border-b px-6 py-4 flex items-center justify-between">
      <span className="font-semibold text-lg">App</span>
      <div className="flex items-center gap-1">
        {(['pl', 'en'] as const).map((lang) => (
          <button
            key={lang}
            onClick={() => i18n.changeLanguage(lang)}
            className={`px-2 py-1 text-xs rounded font-medium transition-colors ${
              i18n.language === lang
                ? 'bg-slate-800 text-white'
                : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'
            }`}
          >
            {lang.toUpperCase()}
          </button>
        ))}
      </div>
    </header>
  )
}
