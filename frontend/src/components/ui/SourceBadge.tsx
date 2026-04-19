import type { LegalSource } from '../../types'

const sourceColors: Record<LegalSource, string> = {
  'ISAP': 'bg-blue-100 text-blue-700',
  'EUR-Lex': 'bg-indigo-100 text-indigo-700',
  'URE': 'bg-purple-100 text-purple-700',
  'UOKiK': 'bg-pink-100 text-pink-700',
  'ENTSO-E': 'bg-cyan-100 text-cyan-700',
  'PSE': 'bg-teal-100 text-teal-700',
}

export function SourceBadge({ source }: { source: LegalSource }) {
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${sourceColors[source]}`}>
      {source}
    </span>
  )
}
