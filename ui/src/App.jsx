import React, { useState, useCallback, useEffect, useRef } from 'react'
import MetricStrip from './components/MetricStrip.jsx'
import ActionLog from './components/ActionLog.jsx'
import RouteMap from './components/RouteMap.jsx'
import NodeSidePanel from './components/NodeSidePanel.jsx'
import LlmReasoningPanel from './components/LlmReasoningPanel.jsx'

const SIM_MAX = 430

// T-2h before each incident's detection fires
const DEMO_JUMPS = [
  { id: 'inc1', label: '▶ Demo: INC-1', h: 245.5, tip: 'INC-1: RuPay/HDFC Degradation (94%→82%)' },
  { id: 'inc2', label: '▶ Demo: INC-2', h: 307.7, tip: 'INC-2: Cross-Border Route B (96%→84%)' },
  { id: 'inc3', label: '▶ Demo: INC-3', h: 365.6, tip: 'INC-3: UPI AutoPay Paytm (93%→85%)' },
]

const NAV_JUMPS = [
  { id: 'h0',   label: 'h=0 (Nominal)', h: 0   },
  { id: 'nav1', label: 'INC-1 (h=241)', h: 241 },
  { id: 'nav2', label: 'INC-2 (h=301)', h: 301 },
  { id: 'nav3', label: 'INC-3 (h=361)', h: 361 },
]

export default function App() {
  const [approvalLog,   setApprovalLog]   = useState([])
  const [selectedRoute, setSelectedRoute] = useState(null)
  const [simHour,       setSimHour]       = useState(245.5) // start at active demo point
  const [activeJumpId,  setActiveJumpId]  = useState('inc1') // track active clicked button
  const [simSpeed,      setSimSpeed]      = useState(10) // 10 sim-hours per real second
  const [playing,       setPlaying]       = useState(false)
  const [logOpen,       setLogOpen]       = useState(false)
  const [llmPanelOpen,  setLlmPanelOpen]  = useState(false)
  const [resetKey,      setResetKey]      = useState(0)

  const lastTsRef  = useRef(null)
  const simHourRef = useRef(simHour)
  const simSpeedRef = useRef(simSpeed)
  useEffect(() => { simHourRef.current = simHour }, [simHour])
  useEffect(() => { simSpeedRef.current = simSpeed }, [simSpeed])

  // rAF sim clock
  useEffect(() => {
    if (!playing) return
    let rafId
    const tick = (ts) => {
      if (lastTsRef.current !== null) {
        const dtSec = Math.min((ts - lastTsRef.current) / 1000, 0.1)
        setSimHour(h => {
          const next = h + dtSec * simSpeedRef.current
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

  const togglePlay = useCallback(() => {
    setPlaying(prev => {
      const next = !prev
      if (next && simHour < 10) {
        setSimHour(245.5)
        setActiveJumpId('inc1')
      }
      return next
    })
  }, [simHour])

  const jumpTo = useCallback((h, id = null, autoPlay = true) => {
    setSimHour(h)
    if (id) setActiveJumpId(id)
    if (autoPlay) setPlaying(true)
  }, [])

  const handleReset = useCallback(() => {
    setPlaying(false)
    setSimHour(0)
    setActiveJumpId('h0')
    setApprovalLog([])
    setSelectedRoute(null)
    setLogOpen(false)
    setResetKey(k => k + 1)
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

  const toggleSpeed = useCallback(() => {
    setSimSpeed(s => (s === 3 ? 10 : s === 10 ? 25 : 3))
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
        className="flex items-center gap-2 px-4 py-1.5 border-b border-border shrink-0 overflow-x-auto"
        style={{ background: '#141B26' }}
      >
        {/* Play / pause */}
        <button
          onClick={togglePlay}
          className="font-mono text-[10px] px-2.5 py-1 border border-border hover:border-signal-blue transition-colors shrink-0 flex items-center gap-1.5"
          style={{ color: playing ? '#5B8DEF' : '#E8ECF1', background: playing ? '#5B8DEF1E' : '#141B26' }}
          title={playing ? 'Pause simulation clock' : 'Play simulation clock'}
        >
          <span>{playing ? '⏸ LIVE PLAYING' : '▶ START LIVE'}</span>
        </button>

        {/* Speed toggle */}
        <button
          onClick={toggleSpeed}
          className="font-mono text-[9px] px-1.5 py-1 border border-border hover:border-signal-blue transition-colors shrink-0 text-muted"
          title="Click to cycle speed: 3x -> 10x -> 25x"
        >
          SPEED: <span className="text-signal-blue font-semibold">{simSpeed}h/s</span>
        </button>

        {/* Reset */}
        <button
          onClick={handleReset}
          className="font-mono text-[9px] px-2 py-1 border border-border hover:border-red transition-colors shrink-0 text-muted"
          title="Reset simulation to h=0"
        >
          ↺ RESET
        </button>

        {/* Scrubber */}
        <input
          type="range" min="0" max={SIM_MAX} step="0.5"
          value={simHour}
          onChange={e => {
            setPlaying(false)
            setSimHour(Number(e.target.value))
            setActiveJumpId(null)
          }}
          className="flex-1 min-w-[100px]"
          style={{ accentColor: '#5B8DEF' }}
        />
        <span className="font-mono text-[11px] shrink-0 w-24 text-right text-text">
          sim_h <span className="text-signal-blue font-semibold">{simHour.toFixed(1)}</span>
        </span>

        {/* Separator */}
        <div className="w-px h-4 bg-border shrink-0" />

        {/* Demo quick-jump buttons — HIGHLIGHTS ONLY THE ACTIVE CLICKED BUTTON */}
        {DEMO_JUMPS.map(({ id, label, h, tip }) => {
          const isClicked = activeJumpId === id || (Math.abs(simHour - h) < 1.0 && activeJumpId === id)
          return (
            <button
              key={id}
              onClick={() => jumpTo(h, id)}
              title={tip}
              className="font-mono text-[9px] px-2 py-1 border transition-all shrink-0"
              style={{
                borderColor: isClicked ? '#5B8DEF' : '#1E2A3A',
                color:       isClicked ? '#E8ECF1' : '#6B7A90',
                background:  isClicked ? '#5B8DEF2E' : '#141B26',
                fontWeight:  isClicked ? '600' : '400',
                boxShadow:   isClicked ? '0 0 8px rgba(91, 141, 239, 0.35)' : 'none',
              }}
            >
              {label}
            </button>
          )
        })}

        {/* Separator */}
        <div className="w-px h-4 bg-border shrink-0" />

        {/* Nav jumps */}
        {NAV_JUMPS.map(({ id, label, h }) => {
          const isClicked = activeJumpId === id
          return (
            <button
              key={id}
              onClick={() => {
                setPlaying(false)
                jumpTo(h, id, false)
              }}
              className="font-mono text-[9px] px-1.5 py-0.5 border transition-all shrink-0 text-muted"
              style={{
                borderColor: isClicked ? '#5B8DEF' : '#1E2A3A',
                color:       isClicked ? '#5B8DEF' : '#6B7A90',
                background:  isClicked ? '#5B8DEF1A' : 'transparent',
              }}
              title={`Jump clock to sim_h=${h}`}
            >
              {label}
            </button>
          )
        })}

        {/* Separator */}
        <div className="w-px h-4 bg-border shrink-0" />

        {/* Log toggle */}
        <button
          onClick={() => setLogOpen(o => !o)}
          className="font-mono text-[9px] px-2 py-1 border border-border hover:border-signal-blue transition-colors shrink-0"
          style={{ color: logOpen ? '#5B8DEF' : '#6B7A90' }}
          title="Toggle AI Action Log Feed"
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
          title="Toggle LLM Reasoning Transparency Panel (Fix 5: ep_1_216)"
        >
          <span>🧠 LLM (SIMULATED)</span>
        </button>
      </div>

      {/* ── Main body ── */}
      <div className="flex flex-1 overflow-hidden relative" style={{ minHeight: 0 }}>

        {/* Hero: network map — key=resetKey forces remount on reset */}
        <div className="flex-1 overflow-hidden" style={{ minWidth: 0 }}>
          <RouteMap
            key={resetKey}
            simHour={simHour}
            isPlaying={playing}
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

        {/* LLM Reasoning Modal Overlay — fully scrollable */}
        {llmPanelOpen && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
            <LlmReasoningPanel onClose={() => setLlmPanelOpen(false)} />
          </div>
        )}

      </div>
    </div>
  )
}
