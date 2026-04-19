import { useTranslation } from 'react-i18next'
import { useSignedDocuments, getDocumentDownloadUrl } from '../services/api'

export function SignedDocumentsPage() {
  const { t, i18n } = useTranslation()
  const { data: documents, isLoading } = useSignedDocuments()

  return (
    <div className="px-8 py-8 max-w-4xl">
      <h1 className="text-xl font-bold text-slate-800 mb-1">{t('contracts:signed.title')}</h1>
      <p className="text-sm text-slate-500 mb-6">{t('contracts:signed.subtitle')}</p>

      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 bg-slate-100 rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && (!documents || documents.length === 0) && (
        <div className="text-center py-16 text-slate-400">
          <div className="text-4xl mb-3">📄</div>
          <div className="text-sm">{t('contracts:signed.empty.title')}</div>
          <div className="text-xs mt-1">{t('contracts:signed.empty.hint')}</div>
        </div>
      )}

      {!isLoading && documents && documents.length > 0 && (
        <div className="space-y-3">
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="bg-white border border-slate-200 rounded-xl p-5 flex items-center justify-between gap-4"
            >
              <div className="flex items-center gap-4 min-w-0">
                <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center shrink-0 text-lg">
                  📄
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-800 truncate">{doc.filename}</div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    Alert: <span className="font-mono">{doc.alertId}</span>
                  </div>
                  {doc.signedAt && (
                    <div className="text-xs text-slate-400 mt-0.5">
                      {t('contracts:signed.signedAt', { date: new Date(doc.signedAt).toLocaleString(i18n.language) })}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-3 shrink-0">
                {doc.signedTxHash && (
                  <div className="text-xs bg-slate-900 text-green-400 font-mono px-3 py-1.5 rounded-lg">
                    ⛓ {doc.signedTxHash.slice(0, 12)}…
                  </div>
                )}
                <a
                  href={getDocumentDownloadUrl(doc.id)}
                  download={doc.filename}
                  className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
                >
                  <span>⬇</span>
                  {t('common:actions.download')}
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
