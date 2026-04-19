import axios from 'axios'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Alert, BlockchainProof, RiskLevel, AlertStatus, DocumentReview, Proposal, ReadReceipt, Contract } from '../types'

export const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
)

// ---------------------------------------------------------------------------
// Backend response shape (matches AlertJson from app/main.py)
// ---------------------------------------------------------------------------

interface ZmianaBackend {
  rodzaj: string
  tekst: string
  artykuł: string
  sekcja: string
  ustęp: string
  punkt: string
}

interface AnchorReceiptBackend {
  backend: string
  chain_id: string
  tx_reference: string
  block_number: number | null
  explorer_url: string | null
  extra: Record<string, unknown>
}

export interface DirectiveBackend {
  address: string
  date: string | null
  title: string
}

interface RelatedChangeBackend {
  id: string
  title: string
  analyzed_at: string | null
  zmiany_count: number
}

export interface RelatedChange {
  id: string
  title: string
  analyzedAt: string | null
  zmianyCount: number
}

export interface BackendAlert {
  id: string
  title: string
  summary: string
  source_url: string | null
  anchor: AnchorReceiptBackend | null
  source?: string
  document_id: string | null
  detected_at: string | null
  published_at: string | null
  status: string
  change_type: string
  risk_level: number
  zmiany: ZmianaBackend[]
  related_changes: RelatedChangeBackend[]
  directives: DirectiveBackend[]
  keywords: string[]
  keywords_names: string[]
  legal_bases: { id: string; art: string }[]
  amended_act: { address: string | null; eli: string | null; title: string | null } | null
  read_receipts?: ReadReceiptBackend[]
}

// ---------------------------------------------------------------------------
// Mapper: BackendAlert → Alert (frontend rich type)
// ---------------------------------------------------------------------------

function mapAnchor(a: AnchorReceiptBackend, timestampIso?: string): BlockchainProof {
  return {
    txHash: a.tx_reference,
    blockNumber: a.block_number ?? 0,
    timestamp: timestampIso ?? new Date().toISOString(),
    chain: 'Polygon',
    verified: true,
  }
}

interface ReadReceiptBackend {
  read_at: string
  reader_ref: string | null
  anchor: AnchorReceiptBackend
}

function mapReadReceipt(r: ReadReceiptBackend): ReadReceipt {
  return {
    readAt: r.read_at,
    readerRef: r.reader_ref,
    anchor: mapAnchor(r.anchor, r.read_at),
  }
}

export function mapToAlert(b: BackendAlert): Alert {
  return {
    id: b.id,
    title: b.title,
    summary: b.summary,
    source: (b.source as Alert['source']) ?? 'ISAP',
    sourceUrl: b.source_url ?? '',
    documentId: b.document_id ?? b.id,
    publishedAt: b.published_at ?? b.detected_at ?? new Date().toISOString(),
    detectedAt: b.detected_at ?? new Date().toISOString(),
    riskLevel: Math.min(Math.max(b.risk_level, 1), 10) as RiskLevel,
    status: (b.status as AlertStatus) ?? 'new',
    changeType: b.change_type as Alert['changeType'],
    affectedClauses: [],
    relatedLaws: [],
    suggestedAction: '',
    diffBefore: '',
    diffAfter: b.zmiany.map((z) => z.tekst).join('\n\n'),
    blockchainProof: b.anchor ? mapAnchor(b.anchor) : null,
    readReceipts: (b.read_receipts ?? []).map(mapReadReceipt),
    relatedChanges: (b.related_changes ?? []).map((r) => ({
      id: r.id,
      title: r.title,
      analyzedAt: r.analyzed_at,
      zmianyCount: r.zmiany_count,
    })),
    directives: (b.directives ?? []).map((d) => ({
      address: d.address,
      date: d.date,
      title: d.title,
    })),
    keywords: b.keywords ?? [],
    keywordsNames: b.keywords_names ?? [],
    zmianyCount: b.zmiany?.length ?? 0,
    zmiany: (b.zmiany ?? []).map((z) => ({
      rodzaj: z.rodzaj,
      tekst: z.tekst,
      artykuł: z.artykuł,
      sekcja: z.sekcja,
      ustęp: z.ustęp,
      punkt: z.punkt,
    })),
    legalBases: (b.legal_bases ?? []).map((lb) => ({ id: lb.id, art: lb.art })),
    amendedAct: b.amended_act ? { address: b.amended_act.address, eli: b.amended_act.eli, title: b.amended_act.title } : null,
  }
}

// ---------------------------------------------------------------------------
// Paginated response shape
// ---------------------------------------------------------------------------

export interface PaginatedAlerts {
  items: Alert[]
  total: number
  page: number
  pages: number
}

interface PaginatedAlertsBackend {
  items: BackendAlert[]
  total: number
  page: number
  pages: number
}

// ---------------------------------------------------------------------------
// React Query hooks
// ---------------------------------------------------------------------------

async function fetchAlerts(page: number, limit: number): Promise<PaginatedAlerts> {
  const { data } = await api.get<PaginatedAlertsBackend>('/alerts', { params: { page, limit } })
  return {
    items: data.items.map(mapToAlert),
    total: data.total,
    page: data.page,
    pages: data.pages,
  }
}

async function fetchAlert(id: string): Promise<Alert> {
  const { data } = await api.get<BackendAlert>(`/alerts/${id}`)
  return mapToAlert(data)
}

async function anchorAlert(id: string): Promise<Alert> {
  const { data } = await api.post<BackendAlert>(`/alerts/${id}/anchor`)
  return mapToAlert(data)
}

interface BackendContract {
  id: string
  name: string
  counterparty: string
  type: string
  valid_until: string
  alert_count: number
}

function mapContract(c: BackendContract): Contract {
  return {
    id: c.id,
    name: c.name,
    counterparty: c.counterparty,
    type: c.type as Contract['type'],
    validUntil: c.valid_until,
    alertCount: c.alert_count,
  }
}

async function postReadReceipt(alertId: string, readerRef: string): Promise<ReadReceipt> {
  const { data } = await api.post<ReadReceiptBackend>(`/alerts/${alertId}/read-receipt`, {
    reader_ref: readerRef,
  })
  return mapReadReceipt(data)
}

async function fetchContracts(): Promise<Contract[]> {
  const { data } = await api.get<BackendContract[]>('/contracts')
  return data.map(mapContract)
}

export function useContracts() {
  return useQuery({
    queryKey: ['contracts'],
    queryFn: fetchContracts,
    staleTime: 120_000,
  })
}

export function useAlerts(page = 1, limit = 25) {
  return useQuery({
    queryKey: ['alerts', page, limit],
    queryFn: () => fetchAlerts(page, limit),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })
}

export function useAlert(id: string) {
  return useQuery({
    queryKey: ['alerts', id],
    queryFn: () => fetchAlert(id),
    enabled: !!id,
    staleTime: 60_000,
  })
}

export interface BackendStats {
  total: number
  high_risk: number
  pending_review: number
  resolved_this_month: number
  last_analyzed_at: string | null
  in_force_count: number
  expiring_soon: { address: string; title: string; expiration_date: string }[]
}

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: async () => {
      const { data } = await api.get<BackendStats>('/stats')
      return data
    },
    staleTime: 60_000,
  })
}

// ---------------------------------------------------------------------------
// ISAP acts browser
// ---------------------------------------------------------------------------

export interface IsapAct {
  address: string
  title: string
  docType: string
  status: string
  inForce: string
  announcementDate: string | null
  expirationDate: string | null
  eli: string | null
  displayAddress: string
  keywords: string[]
  keywordsNames: string[]
  sourceUrl: string | null
}

export interface PaginatedIsap {
  items: IsapAct[]
  total: number
  page: number
  pages: number
}

interface IsapActBackend {
  address: string
  title: string
  doc_type: string
  status: string
  in_force: string
  announcement_date: string | null
  expiration_date: string | null
  eli: string | null
  display_address: string
  keywords: string[]
  keywords_names: string[]
  source_url: string | null
}

interface PaginatedIsapBackend {
  items: IsapActBackend[]
  total: number
  page: number
  pages: number
}

function mapIsapAct(b: IsapActBackend): IsapAct {
  return {
    address: b.address,
    title: b.title,
    docType: b.doc_type,
    status: b.status,
    inForce: b.in_force,
    announcementDate: b.announcement_date,
    expirationDate: b.expiration_date,
    eli: b.eli,
    displayAddress: b.display_address,
    keywords: b.keywords ?? [],
    keywordsNames: b.keywords_names ?? [],
    sourceUrl: b.source_url,
  }
}

export function useIsap(page = 1, limit = 25, q = '', inForce = '', docType = '') {
  return useQuery({
    queryKey: ['isap', page, limit, q, inForce, docType],
    queryFn: async (): Promise<PaginatedIsap> => {
      const { data } = await api.get<PaginatedIsapBackend>('/isap', {
        params: { page, limit, q: q || undefined, in_force: inForce || undefined, doc_type: docType || undefined },
      })
      return {
        items: data.items.map(mapIsapAct),
        total: data.total,
        page: data.page,
        pages: data.pages,
      }
    },
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })
}

export function useAnchorAlert() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: anchorAlert,
    onSuccess: (updated) => {
      queryClient.setQueryData(['alerts', updated.id], updated)
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
    },
  })
}

export function useRecordReadReceipt(alertId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (readerRef: string) => postReadReceipt(alertId, readerRef),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts', alertId] })
    },
  })
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

interface ProposalBackend {
  id: string
  original_text: string
  proposed_text: string
  reason: string
  status: string
  edited_text: string | null
}

interface DocumentBackend {
  id: string
  alert_id: string
  filename: string
  uploaded_at: string
  status: string
  proposals: ProposalBackend[]
  signed_tx_hash: string | null
  signed_at: string | null
}

function mapDocument(b: DocumentBackend): DocumentReview {
  return {
    id: b.id,
    alertId: b.alert_id,
    filename: b.filename,
    uploadedAt: b.uploaded_at,
    status: b.status as DocumentReview['status'],
    proposals: b.proposals.map((p): Proposal => ({
      id: p.id,
      originalText: p.original_text,
      proposedText: p.proposed_text,
      reason: p.reason,
      status: p.status as Proposal['status'],
      editedText: p.edited_text,
    })),
    signedTxHash: b.signed_tx_hash,
    signedAt: b.signed_at,
  }
}

export function useAlertDocuments(alertId: string) {
  return useQuery({
    queryKey: ['documents', alertId],
    queryFn: async (): Promise<DocumentReview[]> => {
      const { data } = await api.get<DocumentBackend[]>(`/alerts/${alertId}/documents`)
      return data.map(mapDocument)
    },
    enabled: !!alertId,
    staleTime: 30_000,
  })
}

export function useUploadDocument(alertId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File): Promise<DocumentReview> => {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post<DocumentBackend>(`/alerts/${alertId}/documents`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return mapDocument(data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', alertId] })
    },
  })
}

export function useDeleteDocument(alertId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (docId: string): Promise<void> => {
      await api.delete(`/documents/${docId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', alertId] })
    },
  })
}

export function useUpdateProposal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      docId,
      proposalId,
      status,
      editedText,
    }: {
      docId: string
      proposalId: string
      status: 'accepted' | 'rejected' | 'edited'
      editedText?: string
    }): Promise<DocumentReview> => {
      const { data } = await api.patch<DocumentBackend>(
        `/documents/${docId}/proposals/${proposalId}`,
        { status, edited_text: editedText ?? null }
      )
      return mapDocument(data)
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(['document', updated.id], updated)
      queryClient.invalidateQueries({ queryKey: ['documents', updated.alertId] })
    },
  })
}

export function useSignDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (docId: string): Promise<DocumentReview> => {
      const { data } = await api.post<DocumentBackend>(`/documents/${docId}/sign`)
      return mapDocument(data)
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['documents', updated.alertId] })
      queryClient.invalidateQueries({ queryKey: ['signed-documents'] })
    },
  })
}

export function useSignedDocuments() {
  return useQuery({
    queryKey: ['signed-documents'],
    queryFn: async (): Promise<DocumentReview[]> => {
      const { data } = await api.get<DocumentBackend[]>('/documents/signed')
      return data.map(mapDocument)
    },
    staleTime: 30_000,
  })
}

export function getDocumentDownloadUrl(docId: string): string {
  return `/api/documents/${docId}/download`
}
