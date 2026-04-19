import { useEffect, useMemo, useState } from 'react'
import * as d3 from 'd3'
import { useTranslation } from 'react-i18next'
import type { Alert } from '../types'

type TFunc = (key: string, options?: unknown) => string

// ── Types ──────────────────────────────────────────────────────────────────────

type NodeType = 'alert' | 'primary_law' | 'related_law' | 'clause' | 'directive' | 'reference_law' | 'amended_act'

interface GraphNode extends d3.SimulationNodeDatum {
  id: string
  type: NodeType
  label: string
  sublabel?: string
  relevance?: number
  riskLevel?: number
  hasBlockchain?: boolean
}

interface GraphEdge extends d3.SimulationLinkDatum<GraphNode> {
  id: string
  type: 'triggers' | 'related' | 'affects'
  relevance?: number
}

interface ResolvedEdge extends GraphEdge {
  sx: number; sy: number; tx: number; ty: number
}

// ── Builder ────────────────────────────────────────────────────────────────────

function buildAlertGraph(alert: Alert, t: TFunc): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []

  // Central alert node
  nodes.push({
    id: 'alert',
    type: 'alert',
    label: t('alerts:graph.risk', { level: alert.riskLevel }),
    sublabel: `AI ${Math.round(Math.max(...alert.affectedClauses.map(c => c.relevanceScore)) * 100)}%`,
    riskLevel: alert.riskLevel,
    hasBlockchain: !!alert.blockchainProof,
  })

  // Primary law node
  nodes.push({
    id: 'primary',
    type: 'primary_law',
    label: alert.documentId.length > 20 ? alert.documentId.slice(0, 20) + '…' : alert.documentId,
    sublabel: alert.source,
    relevance: 1.0,
  })
  edges.push({ id: 'e-primary', source: 'primary', target: 'alert', type: 'triggers', relevance: 1.0 })

  // Related laws
  alert.relatedLaws.forEach((law, i) => {
    const id = `related-${i}`
    nodes.push({
      id,
      type: 'related_law',
      label: law.title.length > 22 ? law.title.slice(0, 22) + '…' : law.title,
      sublabel: law.source,
      relevance: law.relevanceScore,
    })
    edges.push({ id: `e-rel-${i}`, source: id, target: 'alert', type: 'related', relevance: law.relevanceScore })

    // Cross-edges: strong related laws also link to clauses they influence
    if (law.relevanceScore >= 0.7) {
      alert.affectedClauses.forEach((clause, ci) => {
        edges.push({
          id: `e-cross-${i}-${ci}`,
          source: id,
          target: `clause-${ci}`,
          type: 'affects',
          relevance: law.relevanceScore * clause.relevanceScore,
        })
      })
    }
  })

  // Directive nodes
  alert.directives.forEach((dir, i) => {
    const id = `directive-${i}`
    const shortTitle = dir.title.length > 22 ? dir.title.slice(0, 22) + '…' : dir.title
    nodes.push({
      id,
      type: 'directive',
      label: dir.address,
      sublabel: shortTitle,
      relevance: undefined,
    })
    edges.push({ id: `e-dir-${i}`, source: id, target: 'primary', type: 'related' })
  })

  // Legal bases (Podstawa prawna)
  alert.legalBases.forEach((lb, i) => {
    const id = `reflaw-${i}`
    nodes.push({ id, type: 'reference_law', label: lb.id, sublabel: lb.art ? `art. ${lb.art}` : undefined })
    edges.push({ id: `e-reflaw-${i}`, source: id, target: 'primary', type: 'related' })
  })

  // Amended act (akt zmieniany)
  if (alert.amendedAct?.address) {
    const shortTitle = alert.amendedAct.title
      ? (alert.amendedAct.title.length > 22 ? alert.amendedAct.title.slice(0, 22) + '…' : alert.amendedAct.title)
      : alert.amendedAct.address
    nodes.push({
      id: 'amended-act',
      type: 'amended_act',
      label: alert.amendedAct.address,
      sublabel: shortTitle !== alert.amendedAct.address ? shortTitle : undefined,
    })
    edges.push({ id: 'e-amended', source: 'primary', target: 'amended-act', type: 'triggers' })
  }

  // Clause nodes
  alert.affectedClauses.forEach((clause, i) => {
    nodes.push({
      id: `clause-${i}`,
      type: 'clause',
      label: clause.clauseNumber,
      sublabel: clause.contractName.split(' ').slice(0, 3).join(' '),
      relevance: clause.relevanceScore,
    })
    edges.push({
      id: `e-clause-${i}`,
      source: 'alert',
      target: `clause-${i}`,
      type: 'affects',
      relevance: clause.relevanceScore,
    })
  })

  return { nodes, edges }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function riskColor(level?: number): string {
  if (!level) return '#6366f1'
  if (level >= 8) return '#ef4444'
  if (level >= 6) return '#f97316'
  if (level >= 4) return '#eab308'
  return '#22c55e'
}

const NODE_CONFIG: Record<NodeType, { r: number; fill: (n: GraphNode) => string; stroke: string }> = {
  alert: {
    r: 42,
    fill: (n) => riskColor(n.riskLevel),
    stroke: 'rgba(255,255,255,0.25)',
  },
  primary_law: {
    r: 32,
    fill: () => '#4338ca',
    stroke: 'rgba(255,255,255,0.2)',
  },
  related_law: {
    r: 26,
    fill: () => '#1e3a5f',
    stroke: '#3b82f6',
  },
  clause: {
    r: 24,
    fill: () => '#064e3b',
    stroke: '#10b981',
  },
  directive: {
    r: 24,
    fill: () => '#581c87',
    stroke: '#a855f7',
  },
  reference_law: {
    r: 22,
    fill: () => '#78350f',
    stroke: '#f59e0b',
  },
  amended_act: {
    r: 26,
    fill: () => '#7c2d12',
    stroke: '#f97316',
  },
}

const EDGE_CONFIG: Record<GraphEdge['type'], { color: string; dash?: string }> = {
  triggers: { color: '#6366f1' },
  related: { color: '#3b82f6', dash: '6 3' },
  affects: { color: '#10b981' },
}

function curvePath(sx: number, sy: number, tx: number, ty: number): string {
  const dx = tx - sx
  const dy = ty - sy
  const dr = Math.sqrt(dx * dx + dy * dy) * 0.6
  return `M ${sx} ${sy} A ${dr} ${dr} 0 0 1 ${tx} ${ty}`
}

function animDur(relevance?: number, type?: GraphEdge['type']): number {
  if (type === 'related') return 3.5
  if (!relevance) return 3
  return Math.max(0.8, 3.5 - relevance * 2.5)
}

// ── Tooltip ────────────────────────────────────────────────────────────────────

interface TooltipData {
  node: GraphNode
  x: number
  y: number
}

// ── Component ──────────────────────────────────────────────────────────────────

const W = 780
const H = 480

export function AlertGraph({ alert }: { alert: Alert }) {
  const { t } = useTranslation()
  const { nodes: initNodes, edges: initEdges } = useMemo(() => buildAlertGraph(alert, t as unknown as TFunc), [alert, t])
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map())
  const [resolvedEdges, setResolvedEdges] = useState<ResolvedEdge[]>([])
  const [tooltip, setTooltip] = useState<TooltipData | null>(null)

  useEffect(() => {
    const nodes: GraphNode[] = initNodes.map(n => ({ ...n, x: W / 2, y: H / 2 }))
    const edges: GraphEdge[] = initEdges.map(e => ({ ...e }))

    // Alert node pinned to center
    const alertNode = nodes.find(n => n.id === 'alert')
    if (alertNode) { alertNode.fx = W / 2; alertNode.fy = H / 2 }

    const sim = d3.forceSimulation<GraphNode>(nodes)
      .force('link', d3.forceLink<GraphNode, GraphEdge>(edges)
        .id(n => n.id)
        .distance(n => {
          const e = n as unknown as GraphEdge
          if (e.type === 'triggers') return 160
          if (e.type === 'related') return 190
          return 150
        })
        .strength(0.6)
      )
      .force('charge', d3.forceManyBody().strength(-320))
      .force('collide', d3.forceCollide<GraphNode>(n => NODE_CONFIG[n.type].r + 20))
      .force('x', d3.forceX(W / 2).strength(0.04))
      .force('y', d3.forceY(H / 2).strength(0.04))
      .stop()

    sim.tick(250)

    setPositions(new Map(nodes.map(n => [n.id, { x: n.x ?? W / 2, y: n.y ?? H / 2 }])))
    setResolvedEdges(edges.map(e => {
      const src = e.source as GraphNode
      const tgt = e.target as GraphNode
      return { ...e, sx: src.x ?? 0, sy: src.y ?? 0, tx: tgt.x ?? 0, ty: tgt.y ?? 0 }
    }))
  }, [initNodes, initEdges])

  const ARROW_DEFS = [
    { id: 'arr-indigo', color: '#6366f1' },
    { id: 'arr-blue', color: '#3b82f6' },
    { id: 'arr-emerald', color: '#10b981' },
  ]

  function arrowId(type: GraphEdge['type']) {
    if (type === 'triggers') return 'arr-indigo'
    if (type === 'related') return 'arr-blue'
    return 'arr-emerald'
  }

  return (
    <div className="relative">
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        className="rounded-xl"
        style={{ background: 'linear-gradient(135deg, #060b18 0%, #0f172a 100%)' }}
      >
        <defs>
          {ARROW_DEFS.map(({ id, color }) => (
            <marker key={id} id={id} viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill={color} opacity={0.8} />
            </marker>
          ))}

          {/* Glow filters */}
          {[
            ['glow-alert-red', '#ef4444', 8],
            ['glow-alert-orange', '#f97316', 8],
            ['glow-alert-yellow', '#eab308', 6],
            ['glow-primary', '#4338ca', 6],
            ['glow-clause', '#10b981', 5],
            ['glow-directive', '#a855f7', 5],
            ['glow-reflaw', '#f59e0b', 5],
            ['glow-amended', '#f97316', 5],
          ].map(([id, color, blur]) => (
            <filter key={id as string} id={id as string}>
              <feGaussianBlur stdDeviation={blur as number} result="blur" />
              <feFlood floodColor={color as string} floodOpacity="0.5" result="color" />
              <feComposite in="color" in2="blur" operator="in" result="glow" />
              <feMerge><feMergeNode in="glow" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          ))}

          {/* Grid */}
          <pattern id="agrid" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M 32 0 L 0 0 0 32" fill="none" stroke="rgba(255,255,255,0.018)" strokeWidth="1" />
          </pattern>
        </defs>

        <rect width={W} height={H} fill="url(#agrid)" />

        {/* Legend */}
        {[
          { color: '#4338ca', label: t('alerts:graph.legend.primary_law'), dash: '' },
          { color: '#a855f7', label: t('alerts:graph.legend.directive'), dash: '5 3' },
          { color: '#f59e0b', label: t('alerts:graph.legend.reference_law'), dash: '5 3' },
          { color: '#f97316', label: t('alerts:graph.legend.amended_act'), dash: '' },
          { color: '#10b981', label: t('alerts:graph.legend.affects'), dash: '' },
        ].map(({ color, label, dash }, i) => (
          <g key={label} transform={`translate(${14 + i * 148}, 14)`}>
            <line x1={0} y1={6} x2={22} y2={6} stroke={color} strokeWidth={1.5}
              strokeDasharray={dash || undefined} />
            <text x={26} y={10} fill="#475569" fontSize={9} fontFamily="system-ui">{label}</text>
          </g>
        ))}

        {/* Edges */}
        {resolvedEdges.map(edge => {
          const cfg = EDGE_CONFIG[edge.type as GraphEdge['type']]
          const path = curvePath(edge.sx, edge.sy, edge.tx, edge.ty)
          const strokeW = edge.type === 'triggers' ? 2 :
            edge.type === 'related' ? 1 + (edge.relevance ?? 0.5) * 1.5 :
            0.5 + (edge.relevance ?? 0.5) * 2
          const dur = animDur(edge.relevance, edge.type as GraphEdge['type'])
          const showDot = edge.type !== 'affects' || (edge.relevance ?? 0) >= 0.6

          return (
            <g key={edge.id}>
              <path d={path} fill="none"
                stroke={cfg.color}
                strokeWidth={strokeW}
                strokeOpacity={edge.type === 'affects' ? 0.3 : 0.45}
                strokeDasharray={cfg.dash}
                markerEnd={`url(#${arrowId(edge.type as GraphEdge['type'])})`}
              />
              {showDot && (
                <circle r={edge.type === 'triggers' ? 3.5 : 2.5} fill={cfg.color} opacity={0.9}>
                  <animateMotion dur={`${dur}s`} repeatCount="indefinite" path={path} rotate="auto" />
                </circle>
              )}
            </g>
          )
        })}

        {/* Nodes */}
        {initNodes.map(node => {
          const pos = positions.get(node.id)
          if (!pos) return null
          const { x, y } = pos
          const cfg = NODE_CONFIG[node.type]
          const fill = cfg.fill(node)
          const isAlert = node.type === 'alert'
          const glowId = isAlert
            ? node.riskLevel! >= 8 ? 'glow-alert-red'
              : node.riskLevel! >= 6 ? 'glow-alert-orange'
              : 'glow-alert-yellow'
            : node.type === 'primary_law' ? 'glow-primary'
            : node.type === 'clause' ? 'glow-clause'
            : node.type === 'directive' ? 'glow-directive'
            : node.type === 'reference_law' ? 'glow-reflaw'
            : node.type === 'amended_act' ? 'glow-amended'
            : undefined

          return (
            <g key={node.id}
              transform={`translate(${x},${y})`}
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setTooltip({ node, x, y })}
              onMouseLeave={() => setTooltip(null)}
            >
              {/* Glow backdrop */}
              {glowId && (
                <circle r={cfg.r + 3} fill={fill} opacity={0.15} filter={`url(#${glowId})`} />
              )}

              {/* Pulse for alert node */}
              {isAlert && (
                <circle r={cfg.r + 5} fill="none" stroke={fill} strokeWidth={1.5} opacity={0.2}>
                  <animate attributeName="r" values={`${cfg.r + 3};${cfg.r + 18};${cfg.r + 3}`} dur="2.5s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0.3;0;0.3" dur="2.5s" repeatCount="indefinite" />
                </circle>
              )}

              {/* Node circle */}
              <circle r={cfg.r} fill={fill} stroke={cfg.stroke} strokeWidth={1.5} />

              {/* Primary label */}
              <text textAnchor="middle" fill="white" fontFamily="system-ui"
                fontSize={isAlert ? 13 : node.type === 'primary_law' ? 9 : 8}
                fontWeight={isAlert ? '800' : '600'}
                dy={node.sublabel ? -5 : 4}>
                {node.label}
              </text>

              {/* Sublabel */}
              {node.sublabel && (
                <text textAnchor="middle" fill="rgba(255,255,255,0.55)"
                  fontFamily="system-ui" fontSize={7.5} dy={7}>
                  {node.sublabel}
                </text>
              )}

              {/* Blockchain badge */}
              {node.hasBlockchain && (
                <text textAnchor="middle" fontSize={9} dy={-cfg.r + 10}>⛓</text>
              )}

              {/* Relevance arc on related/clause nodes */}
              {node.relevance !== undefined && node.type !== 'alert' && (
                <text textAnchor="middle" fill="rgba(255,255,255,0.4)"
                  fontFamily="ui-monospace, monospace" fontSize={7}
                  dy={cfg.r + 11}>
                  {Math.round(node.relevance * 100)}%
                </text>
              )}
            </g>
          )
        })}
      </svg>

      {/* Tooltip */}
      {tooltip && (() => {
        const scaleX = 780
        const pct = tooltip.x / scaleX
        const onLeft = pct > 0.65
        return (
          <div
            className="absolute z-20 pointer-events-none bg-slate-800/95 backdrop-blur text-white text-xs rounded-xl px-3.5 py-3 shadow-2xl border border-slate-600/40 w-56"
            style={{
              left: onLeft ? 'auto' : `calc(${(tooltip.x / scaleX) * 100}% + 20px)`,
              right: onLeft ? `calc(${((scaleX - tooltip.x) / scaleX) * 100}% + 20px)` : 'auto',
              top: `calc(${(tooltip.y / H) * 100}% - 40px)`,
            }}
          >
            <TypeLabel type={tooltip.node.type} />
            <div className="font-semibold mt-1 leading-snug">{tooltip.node.label}</div>
            {tooltip.node.sublabel && (
              <div className="text-slate-400 text-xs mt-0.5">{tooltip.node.sublabel}</div>
            )}
            {tooltip.node.riskLevel && (
              <div className="mt-2 flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full" style={{ background: riskColor(tooltip.node.riskLevel) }} />
                <span>{t('alerts:graph.risk', { level: tooltip.node.riskLevel })}</span>
              </div>
            )}
            {tooltip.node.relevance !== undefined && tooltip.node.type !== 'alert' && (
              <div className="text-emerald-400 mt-1 font-mono">
                {t('alerts:graph.aiRelevance', { pct: Math.round(tooltip.node.relevance * 100) })}
              </div>
            )}
            {tooltip.node.hasBlockchain && (
              <div className="text-emerald-400 mt-1">{t('alerts:graph.savedOnChain')}</div>
            )}
          </div>
        )
      })()}
    </div>
  )
}

function TypeLabel({ type }: { type: NodeType }) {
  const { t } = useTranslation()
  const cls: Record<NodeType, string> = {
    alert: 'text-red-400',
    primary_law: 'text-indigo-400',
    related_law: 'text-blue-400',
    clause: 'text-emerald-400',
    directive: 'text-purple-400',
    reference_law: 'text-amber-400',
    amended_act: 'text-orange-400',
  }
  return (
    <span className={`text-xs font-semibold uppercase tracking-wide ${cls[type]}`}>
      {t(`alerts:graph.nodeType.${type}`, type)}
    </span>
  )
}
