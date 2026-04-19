import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAlerts, useStats } from '../services/api'
import { RiskBadge } from '../components/ui/RiskBadge'
import { SourceBadge } from '../components/ui/SourceBadge'
import { StatusBadge } from '../components/ui/StatusBadge'

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border p-5 ${accent ? 'bg-red-50 border-red-200' : 'bg-white border-slate-200'}`}>
      <div className={`text-3xl font-bold ${accent ? 'text-red-600' : 'text-slate-800'}`}>{value}</div>
      <div className="text-sm font-medium text-slate-600 mt-1">{label}</div>
      {sub && <div className="text-xs text-slate-400 mt-0.5">{sub}</div>}
    </div>
  )
}

function SkeletonRow() {
  return (
    <div className="flex items-start gap-4 px-5 py-4 animate-pulse">
      <div className="w-8 h-6 bg-slate-200 rounded" />
      <div className="flex-1 space-y-2">
        <div className="h-4 bg-slate-200 rounded w-3/4" />
        <div className="h-3 bg-slate-100 rounded w-1/3" />
      </div>
    </div>
  )
}

export function DashboardPage() {
  const { t, i18n } = useTranslation()
  const { data, isLoading, isError } = useAlerts(1, 6)
  const { data: stats } = useStats()
  const recent = data?.items ?? []

  function timeAgo(iso: string): string {
    const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
    if (mins < 60) return t('alerts:timeAgo.minutes', { count: mins })
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return t('alerts:timeAgo.hours', { count: hrs })
    return t('alerts:timeAgo.days', { count: Math.floor(hrs / 24) })
  }

  const totalAlerts = stats?.total ?? 0
  const highRiskAlerts = stats?.high_risk ?? 0
  const pendingReview = stats?.pending_review ?? 0
  const resolvedThisMonth = stats?.resolved_this_month ?? 0
  const inForceCount = stats?.in_force_count ?? 0
  const expiringSoon = stats?.expiring_soon ?? []
  const lastScanAt = stats?.last_analyzed_at ?? recent[0]?.detectedAt

  return (
    <div className="px-8 py-8 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-800">{t('alerts:dashboard.title')}</h1>
        <p className="text-sm text-slate-500 mt-1">
          {lastScanAt
            ? <>{t('alerts:dashboard.lastScan')} <span className="font-medium">{timeAgo(lastScanAt)}</span>&nbsp;·&nbsp;</>
            : null}
          {t('alerts:dashboard.monitoredSources', { count: 5 })}
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-5 gap-4 mb-8">
        <StatCard label={t('alerts:dashboard.stats.totalAlerts')} value={isLoading ? '…' : totalAlerts} />
        <StatCard label={t('alerts:dashboard.stats.highRisk')} value={isLoading ? '…' : highRiskAlerts} accent />
        <StatCard label={t('alerts:dashboard.stats.pendingReview')} value={isLoading ? '…' : pendingReview} sub={t('alerts:dashboard.stats.pendingReviewSub')} />
        <StatCard label={t('alerts:dashboard.stats.resolvedThisMonth')} value={isLoading ? '…' : resolvedThisMonth} />
        <StatCard label={t('alerts:dashboard.stats.inForce')} value={isLoading ? '…' : inForceCount} sub={t('alerts:dashboard.stats.inForceSub')} />
      </div>

      {/* Expiring soon */}
      {expiringSoon.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 mb-8">
          <h2 className="text-sm font-semibold text-amber-700 uppercase tracking-wide mb-3">
            {t('alerts:dashboard.expiringSoon', { count: expiringSoon.length })}
          </h2>
          <div className="space-y-2">
            {expiringSoon.map((act) => (
              <div key={act.address} className="flex items-center justify-between text-sm">
                <span className="text-amber-900 font-mono text-xs">{act.address}</span>
                <span className="text-amber-700 text-xs font-medium">
                  {new Date(act.expiration_date).toLocaleDateString(i18n.language)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}


      {/* Recent alerts */}
      <div className="bg-white border border-slate-200 rounded-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">{t('alerts:dashboard.recentAlerts')}</h2>
          <Link to="/alerts" className="text-sm text-blue-600 hover:underline font-medium">
            {t('common:actions.showAll')}
          </Link>
        </div>

        <div className="divide-y divide-slate-100">
          {isLoading && [1, 2, 3, 4].map((i) => <SkeletonRow key={i} />)}

          {isError && (
            <div className="px-5 py-8 text-center text-sm text-red-500">
              {t('alerts:errors.load')}
            </div>
          )}

          {!isLoading && !isError && recent.length === 0 && (
            <div className="px-5 py-8 text-center text-sm text-slate-400">
              {t('alerts:dashboard.noAlerts')}
            </div>
          )}

          {recent.map((alert) => (
            <Link
              key={alert.id}
              to={`/alerts/${alert.id}`}
              className="flex items-start gap-4 px-5 py-4 hover:bg-slate-50 transition-colors"
            >
              <div className="pt-0.5">
                <RiskBadge level={alert.riskLevel} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-800 truncate">{alert.title}</div>
                <div className="flex items-center gap-2 mt-1">
                  <SourceBadge source={alert.source} />
                  <StatusBadge status={alert.status} />
                  <span className="text-xs text-slate-400">{timeAgo(alert.detectedAt)}</span>
                </div>
              </div>
              {alert.blockchainProof && (
                <div className="shrink-0 text-xs text-green-600 font-medium flex items-center gap-1 bg-green-50 px-2 py-0.5 rounded">
                  <span>⛓</span> on-chain
                </div>
              )}
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
