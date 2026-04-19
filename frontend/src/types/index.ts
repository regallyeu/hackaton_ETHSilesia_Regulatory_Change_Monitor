export type RiskLevel = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10

export type AlertStatus = 'new' | 'reviewing' | 'resolved' | 'ignored'

export type LegalSource =
  | 'ISAP'
  | 'EUR-Lex'
  | 'URE'
  | 'UOKiK'
  | 'ENTSO-E'
  | 'PSE'

export interface RelatedLaw {
  documentId: string
  title: string
  source: LegalSource | 'NIS2' | 'GDPR' | 'KEP'
  relationship: string
  relevanceScore: number
}

export interface AffectedClause {
  contractId: string
  contractName: string
  clauseNumber: string
  clauseTitle: string
  relevanceScore: number
}

export interface BlockchainProof {
  txHash: string
  blockNumber: number
  timestamp: string
  chain: 'Polygon' | 'Hyperledger'
  verified: boolean
}

/** Immutable proof that a viewer opened the alert (anchored payload: alert id + time + reader ref). */
export interface ReadReceipt {
  readAt: string
  readerRef: string | null
  anchor: BlockchainProof
}

export interface Zmiana {
  rodzaj: string
  tekst: string
  artykuł: string
  sekcja: string
  ustęp: string
  punkt: string
}

export interface LegalBase {
  id: string
  art: string
}

export interface AmendedAct {
  address: string | null
  eli: string | null
  title: string | null
}

export interface ExpiringAct {
  address: string
  title: string
  expirationDate: string
}

export interface Directive {
  address: string
  date: string | null
  title: string
}

export interface RelatedChange {
  id: string
  title: string
  analyzedAt: string | null
  zmianyCount: number
}

export interface Alert {
  id: string
  title: string
  source: LegalSource
  sourceUrl: string
  documentId: string
  publishedAt: string
  detectedAt: string
  riskLevel: RiskLevel
  status: AlertStatus
  summary: string
  changeType: 'new_regulation' | 'amendment' | 'repeal' | 'guidance'
  affectedClauses: AffectedClause[]
  suggestedAction: string
  diffBefore: string
  diffAfter: string
  blockchainProof: BlockchainProof | null
  readReceipts: ReadReceipt[]
  relatedLaws: RelatedLaw[]
  relatedChanges: RelatedChange[]
  directives: Directive[]
  keywords: string[]
  keywordsNames: string[]
  zmianyCount: number
  zmiany: Zmiana[]
  legalBases: LegalBase[]
  amendedAct: AmendedAct | null
}

export type ProposalStatus = 'pending' | 'accepted' | 'rejected' | 'edited'

export interface Proposal {
  id: string
  originalText: string
  proposedText: string
  reason: string
  status: ProposalStatus
  editedText: string | null
}

export type DocumentStatus = 'draft' | 'reviewed' | 'signed'

export interface DocumentReview {
  id: string
  alertId: string
  filename: string
  uploadedAt: string
  status: DocumentStatus
  proposals: Proposal[]
  signedTxHash: string | null
  signedAt: string | null
}

export interface Contract {
  id: string
  name: string
  counterparty: string
  type: 'PPA' | 'grid_connection' | 'supply' | 'service'
  validUntil: string
  alertCount: number
}

export interface SystemStats {
  totalAlerts: number
  highRiskAlerts: number
  pendingReview: number
  resolvedThisMonth: number
  lastScanAt: string
  monitoredSources: number
}
