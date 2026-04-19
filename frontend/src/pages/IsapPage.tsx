import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useIsap } from '../services/api'
import type { IsapAct } from '../services/api'

const ALL = ''
const PAGE_SIZE = 25

const IN_FORCE_CSS: Record<string, string> = {
  IN_FORCE:     'bg-green-100 text-green-700 border-green-200',
  NOT_IN_FORCE: 'bg-slate-100 text-slate-500 border-slate-200',
  REPEALED:     'bg-red-100 text-red-600 border-red-200',
  EXPIRED:      'bg-amber-100 text-amber-700 border-amber-200',
}

function InForceBadge({ value }: { value: string }) {
  const { t } = useTranslation()
  const cls = IN_FORCE_CSS[value] ?? 'bg-slate-100 text-slate-500 border-slate-200'
  return (
    <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded border ${cls}`}>
      {t(`isap:inForce.${value}`, value || '—')}
    </span>
  )
}

function formatDate(val: string | null | undefined, locale: string) {
  if (!val) return '—'
  return new Date(val).toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function Pagination({ page, pages, total, limit, onChange }: {
  page: number; pages: number; total: number; limit: number; onChange: (p: number) => void
}) {
  const { t } = useTranslation()
  const from = (page - 1) * limit + 1
  const to = Math.min(page * limit, total)
  const nums: (number | '...')[] = []
  for (let i = 1; i <= pages; i++) {
    if (i === 1 || i === pages || (i >= page - 2 && i <= page + 2)) nums.push(i)
    else if (nums[nums.length - 1] !== '...') nums.push('...')
  }
  return (
    <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100">
      <span className="text-xs text-slate-400">{t('isap:table.showing', { from, to, total })}</span>
      <div className="flex items-center gap-1">
        <button onClick={() => onChange(page - 1)} disabled={page === 1}
          className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
          {t('common:pagination.previous')}
        </button>
        {nums.map((p, i) =>
          p === '...' ? (
            <span key={`e-${i}`} className="px-2 text-xs text-slate-400">…</span>
          ) : (
            <button key={p} onClick={() => onChange(p)}
              className={`w-8 h-8 text-xs rounded-lg border transition-colors ${
                p === page ? 'bg-blue-600 border-blue-600 text-white font-semibold' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}>
              {p}
            </button>
          )
        )}
        <button onClick={() => onChange(page + 1)} disabled={page === pages}
          className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
          {t('common:pagination.next')}
        </button>
      </div>
    </div>
  )
}

function ActDetailPanel({ act, onClose }: { act: IsapAct; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <div className="w-[480px] bg-white shadow-2xl flex flex-col overflow-y-auto">
        <div className="flex items-start justify-between px-6 py-5 border-b border-slate-200 sticky top-0 bg-white z-10">
          <div className="pr-4">
            <div className="text-xs text-slate-400 font-mono mb-1">{act.displayAddress || act.address}</div>
            <h2 className="text-sm font-bold text-slate-800 leading-snug">{act.title}</h2>
          </div>
          <button onClick={onClose} className="shrink-0 text-slate-400 hover:text-slate-700 text-xl leading-none">×</button>
        </div>

        <div className="px-6 py-5 space-y-5 text-sm">
          <div className="flex flex-wrap gap-2">
            <InForceBadge value={act.inForce} />
            {act.docType && (
              <span className="text-xs px-2 py-0.5 rounded border bg-blue-50 text-blue-700 border-blue-200">
                {t(`isap:docType.${act.docType}`, act.docType)}
              </span>
            )}
            {act.status && (
              <span className="text-xs px-2 py-0.5 rounded border bg-slate-50 text-slate-600 border-slate-200">{act.status}</span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-slate-400 mb-0.5">{t('isap:detail.announcementDate')}</div>
              <div className="font-medium text-slate-700">{formatDate(act.announcementDate, i18n.language)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-400 mb-0.5">{t('isap:detail.expirationDate')}</div>
              <div className="font-medium text-slate-700">{formatDate(act.expirationDate, i18n.language)}</div>
            </div>
          </div>

          <div>
            <div className="text-xs text-slate-400 mb-1">{t('isap:detail.address')}</div>
            <div className="font-mono text-xs text-slate-600 bg-slate-50 rounded px-3 py-2 break-all">{act.address}</div>
          </div>
          {act.eli && (
            <div>
              <div className="text-xs text-slate-400 mb-1">{t('isap:detail.eli')}</div>
              <div className="font-mono text-xs text-slate-600 bg-slate-50 rounded px-3 py-2 break-all">{act.eli}</div>
            </div>
          )}

          {act.keywords.length > 0 && (
            <div>
              <div className="text-xs text-slate-400 mb-2">{t('isap:detail.topics')}</div>
              <div className="flex flex-wrap gap-1.5">
                {act.keywords.map((kw) => (
                  <span key={kw} className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100">{kw}</span>
                ))}
              </div>
            </div>
          )}

          {act.keywordsNames.length > 0 && (
            <div>
              <div className="text-xs text-slate-400 mb-2">{t('isap:detail.entities')}</div>
              <div className="flex flex-wrap gap-1.5">
                {act.keywordsNames.map((n) => (
                  <span key={n} className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">{n}</span>
                ))}
              </div>
            </div>
          )}

          {act.sourceUrl && (
            <a href={act.sourceUrl} target="_blank" rel="noopener noreferrer"
              className="block text-xs text-blue-600 hover:underline break-all">
              {act.sourceUrl}
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

export function IsapPage() {
  const { t, i18n } = useTranslation()
  const [page, setPage] = useState(1)
  const [inputValue, setInputValue] = useState('')
  const [search, setSearch] = useState('')
  const [inForce, setInForce] = useState(ALL)
  const [docType, setDocType] = useState(ALL)
  const [selected, setSelected] = useState<IsapAct | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data, isLoading, isError } = useIsap(page, PAGE_SIZE, search, inForce, docType)

  useEffect(() => { setPage(1) }, [search, inForce, docType])

  function handleSearchChange(val: string) {
    setInputValue(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setSearch(val), 350)
  }

  function clearFilters() {
    setInputValue('')
    setSearch('')
    setInForce(ALL)
    setDocType(ALL)
  }

  const hasFilters = inputValue || inForce || docType

  return (
    <div className="px-8 py-8 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">{t('isap:page.title')}</h1>
        <p className="text-sm text-slate-500 mt-1">
          {data ? t('isap:page.subtitle', { total: data.total.toLocaleString(i18n.language) }) : '…'}
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4 mb-6 bg-white border border-slate-200 rounded-xl p-4">
        <div className="flex flex-col gap-1 flex-1 min-w-64">
          <label className="text-xs text-slate-500 font-medium">{t('common:filters.search')}</label>
          <input
            type="text"
            placeholder={t('isap:filters.searchPlaceholder')}
            value={inputValue}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-500 font-medium">{t('isap:filters.inForce')}</label>
          <select value={inForce} onChange={(e) => setInForce(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value={ALL}>{t('isap:filters.allStatuses')}</option>
            <option value="IN_FORCE">{t('isap:inForce.IN_FORCE')}</option>
            <option value="NOT_IN_FORCE">{t('isap:inForce.NOT_IN_FORCE')}</option>
            <option value="REPEALED">{t('isap:inForce.REPEALED')}</option>
            <option value="EXPIRED">{t('isap:inForce.EXPIRED')}</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-500 font-medium">{t('isap:filters.docType')}</label>
          <select value={docType} onChange={(e) => setDocType(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value={ALL}>{t('isap:filters.allTypes')}</option>
            {['Ustawa', 'Rozporządzenie', 'Obwieszczenie', 'Uchwała', 'Zarządzenie', 'Komunikat', 'Decyzja'].map((dt) => (
              <option key={dt} value={dt}>{t(`isap:docType.${dt}`, dt)}</option>
            ))}
          </select>
        </div>

        {hasFilters && (
          <button onClick={clearFilters}
            className="text-xs text-slate-400 hover:text-slate-600 underline pb-1.5">
            {t('common:filters.clearFilters')}
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-left">
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{t('isap:table.act')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-36">{t('isap:table.type')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-36">{t('isap:table.status')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide">{t('isap:table.topics')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-28">{t('isap:table.published')}</th>
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wide w-28">{t('isap:table.expires')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading && Array.from({ length: 8 }, (_, i) => (
              <tr key={i} className="animate-pulse">
                <td className="px-5 py-4">
                  <div className="h-4 bg-slate-200 rounded w-3/4 mb-1.5" />
                  <div className="h-3 bg-slate-100 rounded w-1/3" />
                </td>
                <td className="px-5 py-4"><div className="w-24 h-5 bg-slate-100 rounded" /></td>
                <td className="px-5 py-4"><div className="w-20 h-5 bg-slate-100 rounded" /></td>
                <td className="px-5 py-4"><div className="w-28 h-4 bg-slate-100 rounded" /></td>
                <td className="px-5 py-4"><div className="w-20 h-4 bg-slate-100 rounded" /></td>
                <td className="px-5 py-4"><div className="w-20 h-4 bg-slate-100 rounded" /></td>
              </tr>
            ))}

            {isError && (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-sm text-red-500">
                  {t('isap:errors.load')}
                </td>
              </tr>
            )}

            {!isLoading && !isError && (!data || data.items.length === 0) && (
              <tr>
                <td colSpan={6} className="py-12 text-center text-slate-400 text-sm">
                  {t('isap:empty.noResults')}
                </td>
              </tr>
            )}

            {(data?.items ?? []).map((act) => (
              <tr key={act.address}
                className="hover:bg-slate-50 transition-colors cursor-pointer"
                onClick={() => setSelected(act)}>
                <td className="px-5 py-4">
                  <div className="font-medium text-slate-800 leading-snug line-clamp-2">{act.title}</div>
                  <div className="text-xs text-slate-400 font-mono mt-0.5">{act.displayAddress || act.address}</div>
                </td>
                <td className="px-5 py-4">
                  {act.docType
                    ? <span className="text-xs px-2 py-0.5 rounded border bg-blue-50 text-blue-700 border-blue-200">
                        {t(`isap:docType.${act.docType}`, act.docType)}
                      </span>
                    : <span className="text-slate-300 text-xs">—</span>}
                </td>
                <td className="px-5 py-4">
                  <InForceBadge value={act.inForce} />
                </td>
                <td className="px-5 py-4">
                  <div className="flex flex-wrap gap-1">
                    {act.keywords.slice(0, 3).map((kw) => (
                      <span key={kw} className="text-xs px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600 border border-blue-100 whitespace-nowrap">{kw}</span>
                    ))}
                    {act.keywords.length > 3 && (
                      <span className="text-xs text-slate-400">+{act.keywords.length - 3}</span>
                    )}
                  </div>
                </td>
                <td className="px-5 py-4 text-xs text-slate-500">{formatDate(act.announcementDate, i18n.language)}</td>
                <td className="px-5 py-4 text-xs text-slate-500">{formatDate(act.expirationDate, i18n.language)}</td>
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

      {selected && <ActDetailPanel act={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
