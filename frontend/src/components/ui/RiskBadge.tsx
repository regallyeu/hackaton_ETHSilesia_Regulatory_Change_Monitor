import { useTranslation } from 'react-i18next'
import type { RiskLevel } from '../../types'

interface RiskBadgeProps {
  level: RiskLevel
  showLabel?: boolean
}

const RISK_CSS: Record<string, string> = {
  critical: 'bg-red-100 text-red-700 border-red-200',
  high: 'bg-orange-100 text-orange-700 border-orange-200',
  medium: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  low: 'bg-green-100 text-green-700 border-green-200',
}

function riskKey(level: RiskLevel): string {
  if (level >= 8) return 'critical'
  if (level >= 6) return 'high'
  if (level >= 4) return 'medium'
  return 'low'
}

export function RiskBadge({ level, showLabel = false }: RiskBadgeProps) {
  const { t } = useTranslation()
  const key = riskKey(level)
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${RISK_CSS[key]}`}>
      <span>{level}/10</span>
      {showLabel && <span>· {t(`alerts:risk.${key}` as const)}</span>}
    </span>
  )
}
