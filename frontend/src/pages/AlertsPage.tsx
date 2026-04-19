import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAlerts } from '../services/api'
import { RiskBadge } from '../components/ui/RiskBadge'
import type { Alert } from '../types'

const ALL = 'all'
const PAGE_SIZE = 25

const CHANGE_TYPE_COLORS: Record<string, string> = {
  new_regulation: 'bg-blue-50 text-blue-700 border-blue-200',
  amendment: 'bg-amber-50 text-amber-700 border-amber-200',
  repeal: 'bg-red-50 text-red-700 border-red-200',
  guidance: 'bg-slate-50 text-slate-600 border-slate-200',
}

function ChangeTypeBadge({ type }: { type: string }) {
  const { t } = useTranslation()
  return (
    <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded border ${CHANGE_TYPE_COLORS[type] ?? 'bg-slate-50 text-slate-600 border-slate-200'}`}>
      {t(`alerts:changeType.${type}`, type)}
    </span>
  )
}

function formatDate(iso: string | undefined, locale: string) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function Pagination({ page, pages, total, limit, onChange }: {
  page: number
  pages: number
  total: number
  limit: number
  onChange: (p: number) => void
}) {
  const { t } = useTranslation()
  const from = (page - 1) * limit + 1
  const to = Math.min(page * limit, total)

  const pageNumbers: (number | '...')[] = []
  for (let i = 1; i <= pages; i++) {
    if (i === 1 || i === pages || (i >= page - 2 && i <= page + 2)) {
      pageNumbers.push(i)
    } else if (pageNumbers[pageNumbers.length - 1] !== '...') {
      pageNumbers.push('...')
    }
  }

  return (
    <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100">
      <span className="text-xs text-slate-400">
        {t('alerts:table.showing', { from, to, total })}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page === 1}
          className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {t('common:pagination.previous')}
        </button>
        {pageNumbers.map((p, i) =>
          p === '...' ? (
            <span key={`e-${i}`} className="px-2 text-xs text-slate-400">…</span>
          ) : (
            <button
              key={p}
              onClick={() => onChange(p)}
              className={`w-8 h-8 text-xs rounded-lg border transition-colors ${
                p === page
                  ? 'bg-blue-600 border-blue-600 text-white font-semibold'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {p}
            </button>
          )
        )}
        <button
          onClick={() => onChange(page + 1)}
          disabled={page === pages}
          className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {t('common:pagination.next')}
        </button>
      </div>
    </div>
  )
}

function matchesSearch(alert: Alert, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    alert.title.toLowerCase().includes(q) ||
    alert.documentId.toLowerCase().includes(q)
  )
}

export function AlertsPage() {
  const { t, i18n } = useTranslation()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [changeTypeFilter, setChangeTypeFilter] = useState<string>(ALL)
  const [minRisk, setMinRisk] = useState(0)

  const { data, isLoading, isError } = useAlerts(page, PAGE_SIZE)
  const alerts = data?.items ?? []

  useEffect(() => { setPage(1) }, [search, changeTypeFilter, minRisk])

  const filtered = alerts.filter((a) => {
    if (!matchesSearch(a, search)) return false
    if (changeTypeFilter !== ALL && a.changeType !== changeTypeFilter) return false
    if (a.riskLevel < minRisk) return false
    return true
  })

  return (
    <div className="px-8 py-8 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">{t('alerts:page.title')}</h1>
        <p className="text-sm text-slate-500 mt-1">
          {data ? t('alerts:page.subtitle', { total: data.total }) : '…'}
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4 mb-6 bg-white border border-slate-200 rounded-xl p-4">
        <div className="flex flex-col gap-1 flex-1 min-w-48">
          <label className="text-xs text-slate-500 font-medium">{t('common:filters.search')}</label>
          <input
            type="text"
            placeholder={t('alerts:filters.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-500 font-medium">{t('alerts:filters.changeType')}</label>
          <select
            value={changeTypeFilter}
            onChange={(e) => setChangeTypeFilter(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={ALL}>{t('alerts:filters.allTypes')}</option>
            <option value="new_regulation">{t('alerts:changeType.new_regulation')}</option>
            <option value="amendment">{t('alerts:changeType.amendment')}</option>
            <option value="guidance">{t('alerts:changeType.guidance')}</option>
            <option value="repeal">{t('alerts:changeType.repeal')}</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-500 font-medium">
            {minRisk > 0 ? t('alerts:filters.minRisk', { value: minRisk }) : t('alerts:filters.minRiskNone')}
          </label>
          <input
            type="range"
            min={0}
            max={9}
            value={minRisk}
            onChange={(e) => setMinRisk(Number(e.target.value))}
            className="w-32 mt-1"
          />
        </div>

        {(search || changeTypeFilter !== ALL || minRisk > 0) && (
          <button
            onClick={() => { setSearch(''); setChangeTypeFilter(ALL); setMinRisk(0) }}
            className="text-xs text-slate-400 hover:text-slate-600 underline pb-1.5"
          >
            {t('common:filters.clearFilters')}
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-left">
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-20">{t('alerts:table.risk')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{t('alerts:table.act')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-40">{t('alerts:table.changeType')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-32 text-center">{t('alerts:table.changes')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{t('alerts:table.topics')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-32">{t('alerts:table.published')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-32">{t('alerts:table.detected')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading && Array.from({ length: 8 }, (_, i) => (
              <tr key={i} className="animate-pulse">
                <td className="px-5 py-4"><div className="w-10 h-6 bg-slate-200 rounded" /></td>
                <td className="px-5 py-4">
                  <div className="h-4 bg-slate-200 rounded w-3/4 mb-1.5" />
                  <div className="h-3 bg-slate-100 rounded w-1/3" />
                </td>
                <td className="px-5 py-4"><div className="w-24 h-5 bg-slate-200 rounded" /></td>
                <td className="px-5 py-4"><div className="w-8 h-5 bg-slate-100 rounded mx-auto" /></td>
                <td className="px-5 py-4"><div className="w-28 h-4 bg-slate-100 rounded" /></td>
                <td className="px-5 py-4"><div className="w-20 h-4 bg-slate-100 rounded" /></td>
                <td className="px-5 py-4"><div className="w-20 h-4 bg-slate-100 rounded" /></td>
              </tr>
            ))}

            {isError && (
              <tr>
                <td colSpan={7} className="px-5 py-10 text-center text-sm text-red-500">
                  {t('alerts:errors.load')}
                </td>
              </tr>
            )}

            {!isLoading && !isError && filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="py-12 text-center text-slate-400 text-sm">
                  {t('alerts:empty.noResults')}
                </td>
              </tr>
            )}

            {filtered.map((alert) => (
              <tr key={alert.id} className="hover:bg-slate-50 transition-colors group">
                <td className="px-5 py-4">
                  <RiskBadge level={alert.riskLevel} />
                </td>
                <td className="px-5 py-4">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0">
                      <Link
                        to={`/alerts/${alert.id}`}
                        className="font-medium text-slate-800 hover:text-blue-600 line-clamp-2 leading-snug"
                      >
                        {alert.title}
                      </Link>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-slate-400 font-mono">{alert.documentId}</span>
                        {alert.blockchainProof && (
                          <span className="text-xs text-green-600 font-medium flex items-center gap-0.5">
                            <span>⛓</span> on-chain
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-4">
                  <ChangeTypeBadge type={alert.changeType} />
                </td>
                <td className="px-5 py-4 text-center text-sm text-slate-700 font-medium">
                  {alert.zmianyCount > 0 ? alert.zmianyCount : <span className="text-slate-300">—</span>}
                </td>
                <td className="px-5 py-4">
                  <div className="flex flex-wrap gap-1">
                    {alert.keywords.slice(0, 3).map((kw) => (
                      <span key={kw} className="text-xs px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600 border border-blue-100 whitespace-nowrap">
                        {kw}
                      </span>
                    ))}
                    {alert.keywords.length > 3 && (
                      <span className="text-xs text-slate-400">+{alert.keywords.length - 3}</span>
                    )}
                  </div>
                </td>
                <td className="px-5 py-4 text-xs text-slate-500">
                  {formatDate(alert.publishedAt, i18n.language)}
                </td>
                <td className="px-5 py-4 text-xs text-slate-500">
                  {formatDate(alert.detectedAt, i18n.language)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {data && data.pages > 1 && (
          <Pagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            limit={PAGE_SIZE}
            onChange={setPage}
          />
        )}
      </div>
    </div>
  )
}
