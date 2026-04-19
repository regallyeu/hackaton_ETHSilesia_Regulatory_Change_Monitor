import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAlert, useAnchorAlert, useAlertDocuments, useUploadDocument, useDeleteDocument, useRecordReadReceipt } from '../services/api'
import { getComplianceReaderRef } from '../utils/readerRef'
import { RiskBadge } from '../components/ui/RiskBadge'
import { SourceBadge } from '../components/ui/SourceBadge'
import { StatusBadge } from '../components/ui/StatusBadge'
import { AlertGraph } from '../components/AlertGraph'
import { DocumentReviewDialog } from '../components/DocumentReviewDialog'
import type { BlockchainProof, Zmiana, DocumentReview, ReadReceipt } from '../types'

type Tab = 'detail' | 'graph' | 'history'

const RODZAJ_CSS: Record<string, string> = {
  dodanie_po_punkcie: 'bg-green-100 text-green-700 border-green-200',
  zastapienie_wyrazow_w_ustepie: 'bg-amber-100 text-amber-700 border-amber-200',
  uchylenie: 'bg-red-100 text-red-700 border-red-200',
}

function RodzajBadge({ rodzaj }: { rodzaj: string }) {
  const { t } = useTranslation()
  const cls = RODZAJ_CSS[rodzaj] ?? 'bg-slate-100 text-slate-600 border-slate-200'
  const label = t(`alerts:rodzaj.${rodzaj}`, t('alerts:rodzaj.nieokreślone'))
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${cls}`}>
      {label}
    </span>
  )
}

function ZmianaCard({ zmiana, index, defaultExpanded }: { zmiana: Zmiana; index: number; defaultExpanded: boolean }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(defaultExpanded)
  const ref = [zmiana.sekcja, zmiana.artykuł && `art. ${zmiana.artykuł}`, zmiana.ustęp && `ust. ${zmiana.ustęp}`, zmiana.punkt && `pkt ${zmiana.punkt}`]
    .filter(Boolean).join(' · ')
  const isLong = zmiana.tekst.length > 300

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 bg-slate-50 border-b border-slate-200">
        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-slate-200 text-slate-600 text-xs font-bold shrink-0">
          {index + 1}
        </span>
        <RodzajBadge rodzaj={zmiana.rodzaj} />
        {ref && <span className="text-xs text-slate-400 font-mono">{ref}</span>}
        {isLong && (
          <button
            onClick={() => setExpanded(e => !e)}
            className="ml-auto text-xs text-blue-600 hover:underline"
          >
            {expanded ? t('common:actions.collapse') : t('common:actions.expand')}
          </button>
        )}
      </div>
      <div className={`px-4 py-3 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap font-mono text-xs ${!expanded && isLong ? 'line-clamp-4' : ''}`}>
        {zmiana.tekst}
      </div>
    </div>
  )
}

function BlockchainCard({ proof }: { proof: NonNullable<BlockchainProof> }) {
  const { t, i18n } = useTranslation()
  const shortHash = `${proof.txHash.slice(0, 10)}...${proof.txHash.slice(-8)}`
  return (
    <div className="bg-slate-900 rounded-xl p-5 text-sm">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-green-400 text-base">⛓</span>
        <span className="text-white font-semibold">{t('alerts:detail.blockchain.title')}</span>
        {proof.verified && (
          <span className="ml-auto text-xs text-green-400 font-medium bg-green-900/40 px-2 py-0.5 rounded">
            {t('alerts:detail.blockchain.verified')}
          </span>
        )}
      </div>
      <div className="space-y-2 text-xs">
        <div className="flex justify-between">
          <span className="text-slate-400">{t('alerts:detail.blockchain.network')}</span>
          <span className="text-slate-200 font-medium">{proof.chain}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">{t('alerts:detail.blockchain.block')}</span>
          <span className="text-slate-200 font-medium">#{proof.blockNumber.toLocaleString()}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-400">{t('alerts:detail.blockchain.timestamp')}</span>
          <span className="text-slate-200 font-medium">{new Date(proof.timestamp).toLocaleString(i18n.language)}</span>
        </div>
        <div className="mt-3 pt-3 border-t border-slate-700">
          <div className="text-slate-400 mb-1">{t('alerts:detail.blockchain.txHash')}</div>
          <div className="text-green-400 font-mono break-all text-xs">{shortHash}</div>
        </div>
      </div>
    </div>
  )
}

function ReadReceiptRow({ receipt }: { receipt: ReadReceipt }) {
  const { t, i18n } = useTranslation()
  const p = receipt.anchor
  const short = `${p.txHash.slice(0, 8)}…${p.txHash.slice(-6)}`
  const refShort = receipt.readerRef
    ? `${receipt.readerRef.slice(0, 6)}…${receipt.readerRef.slice(-4)}`
    : '—'
  return (
    <div className="border-t border-slate-700 pt-2 mt-2 first:border-t-0 first:pt-0 first:mt-0 text-xs">
      <div className="flex justify-between gap-2 text-slate-400">
        <span>{t('alerts:detail.readReceipt.viewer')}</span>
        <span className="text-slate-300 font-mono">{refShort}</span>
      </div>
      <div className="flex justify-between gap-2 mt-1">
        <span className="text-slate-400">{t('alerts:detail.readReceipt.at')}</span>
        <span className="text-slate-200">{new Date(receipt.readAt).toLocaleString(i18n.language)}</span>
      </div>
      <div className="text-green-400/90 font-mono mt-1 break-all">{short}</div>
    </div>
  )
}

export function AlertDetailPage() {
  const { t, i18n } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const [tab, setTab] = useState<Tab>('detail')
  const { data: alert, isLoading, isError } = useAlert(id ?? '')
  const anchorAlert = useAnchorAlert()
  const recordRead = useRecordReadReceipt(id ?? '')
  const { data: documents = [] } = useAlertDocuments(id ?? '')
  const uploadDocument = useUploadDocument(id ?? '')
  const deleteDocument = useDeleteDocument(id ?? '')
  const [reviewDoc, setReviewDoc] = useState<DocumentReview | null>(null)
  const readSent = useRef(false)

  useEffect(() => {
    if (!alert?.id || !id || readSent.current) return
    readSent.current = true
    recordRead.mutate(getComplianceReaderRef())
  }, [alert?.id, id])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    uploadDocument.mutate(file, {
      onSuccess: (doc) => setReviewDoc(doc),
    })
    e.target.value = ''
  }

  if (isLoading) {
    return (
      <div className="px-8 py-8">
        <Link to="/alerts" className="text-blue-600 hover:underline text-sm">{t('alerts:detail.backToAlerts')}</Link>
        <div className="mt-8 animate-pulse space-y-4">
          <div className="h-6 bg-slate-200 rounded w-2/3" />
          <div className="h-4 bg-slate-100 rounded w-1/3" />
        </div>
      </div>
    )
  }

  if (isError || !alert) {
    return (
      <div className="px-8 py-8">
        <Link to="/alerts" className="text-blue-600 hover:underline text-sm">{t('alerts:detail.backToAlerts')}</Link>
        <div className="mt-8 text-slate-500">{t('alerts:detail.notFound')}</div>
      </div>
    )
  }

  return (
    <div className="px-8 py-8 max-w-5xl">
      {reviewDoc && (
        <DocumentReviewDialog
          document={reviewDoc}
          onClose={() => setReviewDoc(null)}
          onSigned={(signed) => setReviewDoc(signed)}
        />
      )}

      <Link to="/alerts" className="text-blue-600 hover:underline text-sm">{t('alerts:detail.backToAlerts')}</Link>

      <div className="mt-6 mb-2 flex flex-wrap items-center gap-3">
        <RiskBadge level={alert.riskLevel} showLabel />
        <SourceBadge source={alert.source} />
        <StatusBadge status={alert.status} />
        <span className="text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded">
          {t(`alerts:changeType.${alert.changeType}`, alert.changeType)}
        </span>
      </div>

      <h1 className="text-xl font-bold text-slate-800 mt-3 mb-1">{alert.title}</h1>
      <div className="text-xs text-slate-400 mb-5">
        {alert.documentId} · {t('alerts:detail.publishedAt')} {new Date(alert.publishedAt).toLocaleDateString(i18n.language)}
        &nbsp;· {t('alerts:detail.detectedAt')} {new Date(alert.detectedAt).toLocaleString(i18n.language)}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-slate-200">
        {(
          [
            ['detail', t('alerts:detail.tabs.detail')],
            ['graph', t('alerts:detail.tabs.graph')],
            ...(alert.relatedChanges.length > 1
              ? [['history', t('alerts:detail.tabs.history', { count: alert.relatedChanges.length })]]
              : []),
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === key
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab: Szczegóły */}
      {tab === 'detail' && (
        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2 space-y-6">
            <section className="bg-white border border-slate-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">{t('alerts:detail.sections.aiAnalysis')}</h2>
              <p className="text-sm text-slate-700 leading-relaxed">{alert.summary}</p>
            </section>

            {alert.zmiany.length > 0 && (
              <section className="bg-white border border-slate-200 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
                  {t('alerts:detail.sections.legalChanges', { count: alert.zmiany.length })}
                </h2>
                <div className="space-y-3">
                  {alert.zmiany.map((z, i) => (
                    <ZmianaCard key={i} zmiana={z} index={i} defaultExpanded={i === 0} />
                  ))}
                </div>
              </section>
            )}

            <section className="bg-white border border-slate-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
                {t('alerts:detail.sections.affectedClauses', { count: alert.affectedClauses.length })}
              </h2>
              <div className="space-y-3">
                {alert.affectedClauses.map((clause, i) => (
                  <div key={i} className="flex items-start gap-4 p-3 bg-slate-50 rounded-lg border border-slate-200">
                    <div className="flex-1">
                      <div className="text-sm font-medium text-slate-800">{clause.contractName}</div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {clause.clauseNumber} · {clause.clauseTitle}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-xs text-slate-400">{t('common:labels.relevance')}</div>
                      <div className="text-sm font-bold text-blue-600">{Math.round(clause.relevanceScore * 100)}%</div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="bg-amber-50 border border-amber-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-amber-700 uppercase tracking-wide mb-2">{t('alerts:detail.sections.suggestedAction')}</h2>
              <p className="text-sm text-amber-900 leading-relaxed">{alert.suggestedAction}</p>
            </section>
          </div>

          <div className="space-y-4">
            {alert.blockchainProof ? (
              <BlockchainCard proof={alert.blockchainProof} />
            ) : (
              <div className="bg-slate-100 border border-slate-200 rounded-xl p-5 text-sm text-slate-500">
                <div className="font-medium text-slate-600 mb-1">{t('alerts:detail.blockchain.label')}</div>
                <p className="text-xs text-slate-500 mb-3">{t('alerts:detail.blockchain.contentHint')}</p>
                {anchorAlert.isPending ? (
                  t('alerts:detail.blockchain.pending')
                ) : (
                  <button
                    type="button"
                    onClick={() => anchorAlert.mutate(alert.id)}
                    className="text-sm font-medium text-blue-600 hover:underline"
                  >
                    {t('alerts:detail.blockchain.anchorContent')}
                  </button>
                )}
              </div>
            )}

            <div className="bg-slate-900 rounded-xl p-5 text-sm border border-slate-700">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-amber-400 text-base">◉</span>
                <span className="text-white font-semibold">{t('alerts:detail.readReceipt.title')}</span>
              </div>
              <p className="text-xs text-slate-400 mb-3 leading-relaxed">{t('alerts:detail.readReceipt.description')}</p>
              {recordRead.isPending && (
                <div className="text-xs text-amber-200/90">{t('alerts:detail.readReceipt.recording')}</div>
              )}
              {recordRead.isError && (
                <div className="text-xs text-red-400">{t('alerts:detail.readReceipt.error')}</div>
              )}
              {alert.readReceipts.length > 0 ? (
                <div className="max-h-48 overflow-y-auto pr-1">
                  {[...alert.readReceipts].reverse().map((r, i) => (
                    <ReadReceiptRow key={`${r.readAt}-${r.anchor.txHash}-${i}`} receipt={r} />
                  ))}
                </div>
              ) : !recordRead.isPending ? (
                <div className="text-xs text-slate-500">{t('alerts:detail.readReceipt.empty')}</div>
              ) : null}
            </div>

            <div className="bg-white border border-slate-200 rounded-xl p-5">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">{t('alerts:detail.sections.yourDocuments')}</h3>
              {documents.length > 0 && (
                <div className="space-y-2 mb-3">
                  {documents.map((doc) => (
                    <div key={doc.id} className="flex items-center gap-1 p-2 rounded-lg border border-slate-100 hover:bg-slate-50 transition-colors">
                      <button
                        onClick={() => setReviewDoc(doc)}
                        className="flex items-center gap-2 min-w-0 flex-1 text-left"
                      >
                        <span className="text-base shrink-0">📄</span>
                        <div className="min-w-0">
                          <div className="text-xs font-medium text-slate-700 truncate">{doc.filename}</div>
                          <div className="text-xs text-slate-400">
                            {doc.status === 'signed'
                              ? t('alerts:detail.docStatus.signed')
                              : doc.status === 'reviewed'
                              ? t('alerts:detail.docStatus.reviewed')
                              : `${doc.proposals.filter((p: { status: string }) => p.status !== 'pending').length}/${doc.proposals.length}`}
                          </div>
                        </div>
                      </button>
                      <button
                        onClick={() => deleteDocument.mutate(doc.id)}
                        disabled={deleteDocument.isPending}
                        className="shrink-0 p-1 rounded text-slate-300 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-40"
                        title="Usuń dokument"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <label className={`flex items-center justify-center gap-2 w-full py-2 rounded-lg border-2 border-dashed text-sm font-medium cursor-pointer transition-colors ${uploadDocument.isPending ? 'border-slate-200 text-slate-300' : 'border-slate-300 text-slate-500 hover:border-blue-400 hover:text-blue-600'}`}>
                {uploadDocument.isPending ? (
                  <><span className="animate-spin">⟳</span> {t('alerts:detail.upload.pending')}</>
                ) : (
                  <>{t('alerts:detail.upload.ready')}</>
                )}
                <input type="file" className="hidden" accept=".pdf,.txt,.doc,.docx,.md" onChange={handleFileChange} disabled={uploadDocument.isPending} />
              </label>
            </div>

            {alert.keywords.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">{t('common:labels.topics')}</h3>
                <div className="flex flex-wrap gap-1.5">
                  {alert.keywords.map((kw) => (
                    <span key={kw} className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
                      {kw}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {alert.keywordsNames.length > 0 && (
              <div className="bg-white border border-slate-200 rounded-xl p-5">
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">{t('common:labels.entities')}</h3>
                <div className="flex flex-wrap gap-1.5">
                  {alert.keywordsNames.map((name) => (
                    <span key={name} className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 border border-slate-200">
                      {name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="bg-white border border-slate-200 rounded-xl p-5 text-sm">
              <h3 className="font-semibold text-slate-700 mb-2">{t('common:labels.source')}</h3>
              <a
                href={alert.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline break-all text-xs"
              >
                {alert.sourceUrl}
              </a>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Powiązania */}
      {tab === 'graph' && (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">
            {t('alerts:detail.graphDescription')}
          </p>
          <AlertGraph alert={alert} />
        </div>
      )}

      {/* Tab: Historia zmian */}
      {tab === 'history' && (
        <div className="max-w-2xl">
          <p className="text-xs text-slate-500 mb-6">
            {t('alerts:detail.historyDescription')}
          </p>
          <div className="relative">
            <div className="absolute left-4 top-0 bottom-0 w-px bg-slate-200" />
            <div className="space-y-0">
              {alert.relatedChanges.map((change, i) => {
                const isCurrent = change.id === alert.id
                return (
                  <div key={change.id} className="relative flex gap-5 pb-6">
                    <div className={`relative z-10 flex items-center justify-center w-8 h-8 rounded-full border-2 shrink-0 ${
                      isCurrent
                        ? 'bg-blue-600 border-blue-600'
                        : 'bg-white border-slate-300'
                    }`}>
                      <span className={`text-xs font-bold ${isCurrent ? 'text-white' : 'text-slate-400'}`}>
                        {i + 1}
                      </span>
                    </div>
                    <div className={`flex-1 rounded-xl border p-4 ${
                      isCurrent
                        ? 'bg-blue-50 border-blue-200'
                        : 'bg-white border-slate-200'
                    }`}>
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <span className={`text-xs font-semibold ${isCurrent ? 'text-blue-700' : 'text-slate-500'}`}>
                          {change.analyzedAt
                            ? new Date(change.analyzedAt).toLocaleDateString(i18n.language, { day: '2-digit', month: 'long', year: 'numeric' })
                            : '—'}
                          {isCurrent && <span className="ml-2 text-blue-600 font-bold">{t('alerts:detail.current')}</span>}
                        </span>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          change.zmianyCount > 0
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-slate-100 text-slate-500'
                        }`}>
                          {t('alerts:history.changes', { count: change.zmianyCount })}
                        </span>
                      </div>
                      <p className="text-sm text-slate-700 leading-snug line-clamp-2">{change.title || change.id}</p>
                      <div className="flex items-center gap-3 mt-2">
                        <span className="text-xs text-slate-400 font-mono">{change.id}</span>
                        {!isCurrent && (
                          <Link
                            to={`/alerts/${change.id}`}
                            className="text-xs text-blue-600 hover:underline"
                          >
                            Zobacz →
                          </Link>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
