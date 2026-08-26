import React, { useState, useCallback, useEffect, useRef } from 'react'
import MetricStrip from './components/MetricStrip.jsx'
import ActionLog from './components/ActionLog.jsx'
import RouteMap from './components/RouteMap.jsx'
import NodeSidePanel from './components/NodeSidePanel.jsx'
import LlmReasoningPanel from './components/LlmReasoningPanel.jsx'

const SIM_SPEED = 3      // sim-hours per real second
const SIM_MAX   = 430

// T-2h before each incident's detection fires
// INC-1 detection at start(240) + latency(7.5) = 247.5 → T-minus = 245.5
const DEMO_JUMPS = [
  { label: '▶ Demo: INC-1',  h: 245.5, hot: true,  tip: 'T−2h before INC-1 detection fires' },
  { label: '▶ Demo: INC-2',  h: 307.7, hot: false, tip: 'T−2h before INC-2 detection fires' },
  { label: '▶ Demo: INC-3',  h: 365.6, hot: false, tip: 'T−2h before INC-3 detection fires' },
]

const NAV_JUMPS = [
  { label: 'h=0',   h: 0   },
  { label: 'INC-1', h: 241 },
  { label: 'INC-2', h: 301 },
  { label: 'INC-3', h: 361 },
]

export default function App() {
  const [approvalLog,   setApprovalLog]   = useState([])
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [simHour,       setSimHour]       = useState(0)
  const [playing,       setPlaying]       = useState(false)
  const [logOpen,       setLogOpen]       = useState(false)
  const [llmPanelOpen,  setLlmPanelOpen]  = useState(false)
  const [resetKey,      setResetKey]      = useState(0)  // increment to remount RouteMap


  const lastTsRef  = useRef(null)
  const simHourRef = useRef(simHour)
  useEffect(() => { simHourRef.current = simHour }, [simHour])

  // rAF sim clock
  useEffect(() => {
    if (!playing) return
    let rafId
    const tick = (ts) => {
      if (lastTsRef.current !== null) {
        const dtSec = Math.min((ts - lastTsRef.current) / 1000, 0.1)
        setSimHour(h => {
          const next = h + dtSec * SIM_SPEED
          if (next >= SIM_MAX) { setPlaying(false); return 0 }
          return next
        })
      }
      lastTsRef.current = ts
      rafId = requestAnimationFrame(tick)
    }
    rafId = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(rafId); lastTsRef.current = null }
  }, [playing])

  const jumpTo = useCallback((h, autoPlay = true) => {
    setSimHour(h)
    if (autoPlay) setPlaying(true)
  }, [])

  const handleReset = useCallback(() => {
    setPlaying(false)
    setSimHour(0)
    setApprovalLog([])
    setSelectedRoute(null)
    setLogOpen(false)
    setResetKey(k => k + 1)   // remount RouteMap → clears all ring state
    lastTsRef.current = null
  }, [])

  const handleApprovalAction = useCallback(({ episode_id, decision, result }) => {
    setApprovalLog(prev => [...prev, {
      ts: result.timestamp,
      stage: 'outcome',
      tier: decision === 'reject' ? 'failure' : result.outcome === 'SUCCESS' ? 'success' : 'failure',
      episode_id,
      text: `${decision.toUpperCase()} → ${result.action}  outcome=${result.outcome}  tool=${result.tool}`,
    }])
  }, [])

  const handleNodeClick = useCallback((route) => {
    setSelectedRoute(prev => prev?.id === route.id ? null : route)
  }, [])

  return (
    <div
      className="flex flex-col"
      style={{ backgroundColor: '#0A0E14', color: '#E8ECF1', height: '100vh', overflow: 'hidden' }}
    >
      {/* ── Slim metric status bar ── */}
      <MetricStrip slim />

      {/* ── Control bar ── */}
      <div
        className="flex items-center gap-2 px-4 py-1.5 border-b border-border shrink-0"
        style={{ background: '#141B26' }}
      >
        {/* Play / pause */}
        <button
          onClick={() => setPlaying(p => !p)}
          className="font-mono text-[10px] px-2 py-1 border border-border hover:border-signal-blue transition-colors shrink-0"
          style={{ color: playing ? '#5B8DEF' : '#6B7A90', minWidth: 52 }}
        >
          {playing ? '⏸ LIVE' : '▶ PLAY'}
        </button>

        {/* Reset */}
        <button
          onClick={handleReset}
          className="font-mono text-[10px] px-2 py-1 border border-border hover:border-red transition-colors shrink-0"
          style={{ color: '#6B7A90' }}
          title="Reset all demo state to t=0"
        >
          ↺ RESET
        </button>

        {/* Scrubber */}
        <input
          type="range" min="0" max={SIM_MAX} step="0.5"
          value={simHour}
          onChange={e => { setPlaying(false); setSimHour(Number(e.target.value)) }}
          className="flex-1"
          style={{ accentColor: '#5B8DEF' }}
        />
        <span className="font-mono text-[11px] shrink-0 w-24 text-right" style={{ color: '#E8ECF1' }}>
          sim_h <span style={{ color: '#5B8DEF' }}>{simHour.toFixed(1)}</span>
        </span>

        {/* Separator */}
        <div className="w-px h-4 bg-border shrink-0" />

        {/* Demo quick-jump buttons (T-minus-2h) */}
        {DEMO_JUMPS.map(({ label, h, hot, tip }) => (
          <button
            key={label}
            onClick={() => jumpTo(h)}
            title={tip}
            className="font-mono text-[9px] px-2 py-1 border transition-colors shrink-0"
            style={{
              borderColor: hot ? '#5B8DEF' : '#1E2A3A',
              color:       hot ? '#5B8DEF' : '#6B7A90',
            }}
          >
            {label}
          </button>
        ))}

        {/* Separator */}
        <div className="w-px h-4 bg-border shrink-0" />

        {/* Nav jumps */}
        {NAV_JUMPS.map(({ label, h }) => (
          <button
            key={label}
            onClick={() => { setPlaying(false); setSimHour(h) }}
            className="font-mono text-[9px] px-1.5 py-0.5 border border-border hover:border-signal-blue transition-colors shrink-0"
            style={{ color: '#6B7A90' }}
          >
            {label}
          </button>
        ))}

        {/* Separator */}
        <div className="w-px h-4 bg-border shrink-0" />

        {/* Log toggle */}
        <button
          onClick={() => setLogOpen(o => !o)}
          className="font-mono text-[9px] px-2 py-1 border border-border hover:border-signal-blue transition-colors shrink-0"
          style={{ color: logOpen ? '#5B8DEF' : '#6B7A90' }}
          title="Toggle Action Log"
        >
          LOG {logOpen ? '▼' : '▶'}
        </button>

        {/* Separator */}
        <div className="w-px h-4 bg-border shrink-0" />

        {/* LLM Reasoning toggle */}
        <button
          onClick={() => setLlmPanelOpen(o => !o)}
          className="font-mono text-[9px] px-2 py-1 border border-signal-blue/50 hover:border-signal-blue transition-colors shrink-0 flex items-center gap-1"
          style={{ color: llmPanelOpen ? '#5B8DEF' : '#E8ECF1', background: llmPanelOpen ? '#5B8DEF1A' : 'transparent' }}
          title="Toggle LLM Reasoning Transparency Panel"
        >
          <span>🧠 LLM (SIMULATED)</span>
        </button>
      </div>

      {/* ── Main body ── */}
      <div className="flex flex-1 overflow-hidden relative" style={{ minHeight: 0 }}>

        {/* Hero: network map — key=resetKey forces remount on reset, clearing ring state */}
        <div className="flex-1 overflow-hidden" style={{ minWidth: 0 }}>
          <RouteMap
            key={resetKey}
            simHour={simHour}
            onNodeClick={handleNodeClick}
            selectedId={selectedRoute?.id}
          />
        </div>

        {/* Side panel — node detail, slides in on click */}
        {selectedRoute && (
          <NodeSidePanel
            route={selectedRoute}
            simHour={simHour}
            onClose={() => setSelectedRoute(null)}
            onApprovalAction={handleApprovalAction}
          />
        )}

        {/* Collapsible Action Log */}
        {logOpen && (
          <div
            className="border-l border-border flex flex-col overflow-hidden shrink-0"
            style={{ width: 360 }}
          >
            <ActionLog extraEntries={approvalLog} />
          </div>
        )}

        {/* LLM Reasoning Modal Overlay */}
        {llmPanelOpen && (
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <LlmReasoningPanel onClose={() => setLlmPanelOpen(false)} />
          </div>
        )}

      </div>
    </div>

  )
}
