import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { DocumentReview, Proposal } from '../types'
import { useUpdateProposal, useSignDocument } from '../services/api'

interface Props {
  document: DocumentReview
  onClose: () => void
  onSigned: (doc: DocumentReview) => void
}

const STATUS_CSS: Record<string, string> = {
  accepted: 'border-green-300 bg-green-50',
  rejected: 'border-red-300 bg-red-50',
  edited: 'border-blue-300 bg-blue-50',
  pending: 'border-slate-200 bg-white',
}

const STATUS_BADGE_CSS: Record<string, string> = {
  accepted: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
  edited: 'bg-blue-100 text-blue-700',
  pending: '',
}

function PreviewText({ url }: { url: string }) {
  const [text, setText] = useState<string | null>(null)
  useEffect(() => {
    fetch(url)
      .then(async (r) => {
        const ct = r.headers.get('content-type') || ''
        if (ct.includes('application/json')) {
          const j = await r.json()
          return j.text as string
        }
        return r.text()
      })
      .then(setText)
      .catch(() => setText('Nie udało się wczytać pliku.'))
  }, [url])
  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 text-xs font-mono text-slate-700 whitespace-pre-wrap leading-relaxed">
      {text ?? '…'}
    </div>
  )
}

function ProposalCard({
  proposal,
  index,
  onAccept,
  onReject,
  onEdit,
  disabled,
}: {
  proposal: Proposal
  index: number
  onAccept: () => void
  onReject: () => void
  onEdit: (text: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState(proposal.proposedText)

  const answered = proposal.status !== 'pending'

  return (
    <div className={`rounded-xl border p-4 transition-colors ${STATUS_CSS[proposal.status]}`}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-5 h-5 rounded-full bg-slate-200 text-slate-600 text-xs font-bold shrink-0">
            {index + 1}
          </span>
          <span className="text-xs text-slate-500 leading-snug">{proposal.reason}</span>
        </div>
        {answered && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded shrink-0 ${STATUS_BADGE_CSS[proposal.status]}`}>
            {t(`documents:status.${proposal.status}`, proposal.status)}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase mb-1">{t('documents:proposal.originalText')}</div>
          <div className="text-xs text-slate-600 bg-slate-100 rounded p-2 min-h-[48px] font-mono leading-relaxed">
            {proposal.originalText}
          </div>
        </div>
        <div>
          <div className="text-xs font-semibold text-slate-400 uppercase mb-1">
            {proposal.status === 'edited' ? t('documents:proposal.editedText') : t('documents:proposal.proposedChange')}
          </div>
          {editing ? (
            <textarea
              className="w-full text-xs text-slate-700 bg-white border border-blue-300 rounded p-2 min-h-[80px] font-mono leading-relaxed resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              autoFocus
            />
          ) : (
            <div className={`text-xs rounded p-2 min-h-[48px] font-mono leading-relaxed ${
              proposal.proposedText
                ? 'text-slate-700 bg-amber-50 border border-amber-200'
                : 'text-slate-400 bg-slate-50 border border-slate-200 italic'
            }`}>
              {proposal.status === 'edited' && proposal.editedText
                ? proposal.editedText
                : proposal.proposedText || 'Brak zalecanej zmiany (klauzula zgodna)'}
            </div>
          )}
        </div>
      </div>

      {!answered && !editing && (
        <div className="flex gap-2">
          <button onClick={onAccept} disabled={disabled}
            className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 transition-colors">
            {t('documents:actions.accept')}
          </button>
          <button onClick={onReject} disabled={disabled}
            className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 transition-colors">
            {t('documents:actions.reject')}
          </button>
          <button onClick={() => { setEditText(proposal.proposedText); setEditing(true) }} disabled={disabled}
            className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-blue-100 text-blue-700 hover:bg-blue-200 disabled:opacity-50 transition-colors">
            {t('documents:actions.edit')}
          </button>
        </div>
      )}

      {editing && (
        <div className="flex gap-2">
          <button onClick={() => { onEdit(editText); setEditing(false) }} disabled={disabled}
            className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
            {t('documents:actions.save')}
          </button>
          <button onClick={() => setEditing(false)}
            className="flex-1 text-xs font-medium py-1.5 rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors">
            {t('documents:actions.cancel')}
          </button>
        </div>
      )}

      {answered && !editing && (
        <button onClick={() => { setEditText(proposal.proposedText); setEditing(true) }} disabled={disabled}
          className="text-xs text-slate-400 hover:text-slate-600 underline">
          {t('documents:actions.changeAnswer')}
        </button>
      )}
    </div>
  )
}

export function DocumentReviewDialog({ document, onClose, onSigned }: Props) {
  const { t } = useTranslation()
  const updateProposal = useUpdateProposal()
  const signDocument = useSignDocument()

  const [localDoc, setLocalDoc] = useState<DocumentReview>(document)
  const [showPreview, setShowPreview] = useState(false)

  const previewUrl = `/api/documents/${localDoc.id}/file`
  const isPdf = localDoc.filename.toLowerCase().endsWith('.pdf')

  const answeredCount = localDoc.proposals.filter((p) => p.status !== 'pending').length
  const totalCount = localDoc.proposals.length
  const allAnswered = totalCount > 0 && answeredCount === totalCount
  const isBusy = updateProposal.isPending || signDocument.isPending

  const handleAction = (
    proposalId: string,
    status: 'accepted' | 'rejected' | 'edited',
    editedText?: string
  ) => {
    updateProposal.mutate(
      { docId: localDoc.id, proposalId, status, editedText },
      { onSuccess: (updated) => setLocalDoc(updated) }
    )
  }

  const handleSign = () => {
    signDocument.mutate(localDoc.id, {
      onSuccess: (signed) => {
        setLocalDoc(signed)
        onSigned(signed)
      },
    })
  }

  const progressPct = totalCount > 0 ? (answeredCount / totalCount) * 100 : 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className={`bg-white rounded-2xl shadow-2xl w-full max-h-[90vh] flex flex-col transition-all duration-200 ${showPreview ? 'max-w-6xl' : 'max-w-3xl'}`}>
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-base font-bold text-slate-800">{t('documents:title')}</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {localDoc.filename} &middot; {t('documents:subtitle', { answered: answeredCount, total: totalCount })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowPreview((v) => !v)}
              className={`text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors ${showPreview ? 'bg-slate-900 text-white border-slate-900' : 'border-slate-300 text-slate-600 hover:bg-slate-50'}`}
            >
              👁 {t('documents:preview')}
            </button>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-600 text-xl font-light leading-none mt-0.5"
              aria-label={t('documents:closeLabel')}
            >
              ✕
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div className="px-6 pt-3 pb-1">
          <div className="w-full bg-slate-100 rounded-full h-1.5">
            <div
              className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Content: preview + proposals */}
        <div className={`flex-1 overflow-hidden flex ${showPreview ? 'flex-row' : 'flex-col'}`}>
          {showPreview && (
            <div className="w-1/2 border-r border-slate-200 flex flex-col">
              <div className="px-4 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wide border-b border-slate-100">
                {localDoc.filename}
              </div>
              {isPdf ? (
                <iframe
                  src={previewUrl}
                  className="flex-1 w-full"
                  title={localDoc.filename}
                />
              ) : (
                <PreviewText url={previewUrl} />
              )}
            </div>
          )}

          {/* Proposals */}
          <div className={`overflow-y-auto px-6 py-4 space-y-3 ${showPreview ? 'w-1/2' : 'flex-1'}`}>
            {localDoc.proposals.length === 0 && (
              <div className="text-sm text-slate-500 text-center py-8">
                {t('documents:noProposals')}
              </div>
            )}
            {localDoc.proposals.map((proposal, i) => (
              <ProposalCard
                key={proposal.id}
                proposal={proposal}
                index={i}
                disabled={isBusy}
                onAccept={() => handleAction(proposal.id, 'accepted')}
                onReject={() => handleAction(proposal.id, 'rejected')}
                onEdit={(text) => handleAction(proposal.id, 'edited', text)}
              />
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-200">
          <button
            onClick={onClose}
            className="text-sm font-medium text-slate-500 hover:text-slate-700 px-4 py-2 rounded-lg hover:bg-slate-100 transition-colors"
          >
            {t('documents:actions.cancel')}
          </button>

          {localDoc.status === 'signed' ? (
            <div className="flex items-center gap-2 text-sm font-medium text-green-700 bg-green-100 px-4 py-2 rounded-lg">
              <span>⛓</span>
              <span>{t('documents:signed')}</span>
            </div>
          ) : (
            <button
              onClick={handleSign}
              disabled={!allAnswered || isBusy}
              className="flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-lg bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {signDocument.isPending ? (
                <span className="animate-spin">⟳</span>
              ) : (
                <span>⛓</span>
              )}
              {t('documents:actions.sign')}
              {!allAnswered && (
                <span className="text-xs text-slate-400 ml-1">
                  {t('documents:actions.remaining', { count: totalCount - answeredCount })}
                </span>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
