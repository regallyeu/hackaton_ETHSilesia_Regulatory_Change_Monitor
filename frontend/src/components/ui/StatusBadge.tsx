import { useTranslation } from 'react-i18next'
import type { AlertStatus } from '../../types'

const STATUS_CSS: Record<AlertStatus, string> = {
  new: 'bg-red-50 text-red-600 border border-red-200',
  reviewing: 'bg-yellow-50 text-yellow-700 border border-yellow-200',
  resolved: 'bg-green-50 text-green-700 border border-green-200',
  ignored: 'bg-gray-100 text-gray-500 border border-gray-200',
}

export function StatusBadge({ status }: { status: AlertStatus }) {
  const { t } = useTranslation()
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${STATUS_CSS[status]}`}>
      {t(`alerts:status.${status}` as const)}
    </span>
  )
}
