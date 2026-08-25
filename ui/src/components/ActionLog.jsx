import React, { useState, useEffect, useRef, useCallback } from 'react'
import { TRACE_LOG_ENTRIES } from '../data/episodeData.js'

const MAX_VISIBLE = 80   // cap the live buffer so it never grows unbounded

const STAGE_STYLE = {
  investigator: { label: 'INV', color: 'text-signal-blue', bg: 'bg-signal-blue/10' },
  strategist:   { label: 'STR', color: 'text-signal-blue', bg: 'bg-signal-blue/10' },
  policy: {
    automatic: { label: 'POL', color: 'text-muted',  bg: 'bg-border/30' },
    approval:  { label: 'POL', color: 'text-amber',  bg: 'bg-amber/10'  },
    human:     { label: 'POL', color: 'text-red',    bg: 'bg-red/10'    },
  },
  action:  { label: 'ACT', color: 'text-text',  bg: 'bg-border/30' },
  outcome: {
    success:  { label: 'OUT', color: 'text-green', bg: 'bg-green/10' },
    failure:  { label: 'OUT', color: 'text-red',   bg: 'bg-red/10'   },
    approval: { label: 'OUT', color: 'text-amber', bg: 'bg-amber/10' },
  },
}

function getStyle(entry) {
  const s = STAGE_STYLE[entry.stage]
  if (!s) return { label: '???', color: 'text-muted', bg: 'bg-border/30' }
  if (entry.stage === 'policy') return s[entry.tier] || s.automatic
  if (entry.stage === 'outcome') return s[entry.tier] || s.failure
  return s
}

function LogLine({ entry }) {
  const style = getStyle(entry)
  const ts = entry.ts.slice(11, 19)  // HH:MM:SS only

  return (
    <div className="log-entry flex items-start gap-3 px-4 py-1.5 border-b border-border/30 hover:bg-panel/60 transition-colors">
      <span className="font-mono text-[10px] text-muted shrink-0 pt-px w-20">{ts}</span>
      <span className={`font-mono text-[10px] font-semibold shrink-0 px-1.5 py-0.5 ${style.color} ${style.bg} w-8 text-center`}>
        {style.label}
      </span>
      <span className="font-mono text-[10px] text-muted shrink-0 w-20 truncate">{entry.episode_id}</span>
      <span className={`font-mono text-[11px] leading-relaxed ${style.color}`}>{entry.text}</span>
    </div>
  )
}

export default function ActionLog({ extraEntries = [] }) {
  const [visible, setVisible] = useState([])
  const [cursor, setCursor] = useState(true)
  const scrollRef    = useRef(null)
  const timerRef     = useRef(null)
  const mountedRef   = useRef(true)   // guard against post-unmount state updates
  const idxRef       = useRef(0)

  // Build the source array once per render so the ticker can read it via ref
  const sourceRef = useRef([])
  sourceRef.current = [...TRACE_LOG_ENTRIES, ...extraEntries]

  // Single-timer ticker — no nested timeouts, one chain only
  useEffect(() => {
    mountedRef.current = true
    idxRef.current = 0

    const tick = () => {
      if (!mountedRef.current) return

      const src = sourceRef.current
      if (idxRef.current < src.length) {
        const entry = src[idxRef.current]
        idxRef.current += 1
        setVisible(v => {
          const next = [...v, entry]
          // Window: keep only the last MAX_VISIBLE entries
          return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next
        })
        timerRef.current = setTimeout(tick, 260 + Math.random() * 180)
      } else {
        // Pause, then restart from beginning
        timerRef.current = setTimeout(() => {
          if (!mountedRef.current) return
          idxRef.current = 0
          setVisible([])
          timerRef.current = setTimeout(tick, 400)
        }, 6000)
      }
    }

    timerRef.current = setTimeout(tick, 600)

    return () => {
      mountedRef.current = false
      clearTimeout(timerRef.current)
    }
  }, [])  // intentionally empty — sourceRef.current is always current via ref

  // Blink cursor
  useEffect(() => {
    const iv = setInterval(() => setCursor(c => !c), 530)
    return () => clearInterval(iv)
  }, [])

  // Auto-scroll
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [visible])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-panel shrink-0 flex items-center justify-between">
        <span className="font-sans text-xs font-medium text-muted uppercase tracking-wider">
          AI Action Log
        </span>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] text-muted">{visible.length} entries</span>
          <div className="flex gap-2 items-center">
            <span className="font-mono text-[9px] px-1 py-px bg-signal-blue/10 text-signal-blue">INV/STR</span>
            <span className="font-mono text-[9px] px-1 py-px bg-amber/10 text-amber">APPROVAL</span>
            <span className="font-mono text-[9px] px-1 py-px bg-red/10 text-red">INCIDENT</span>
            <span className="font-mono text-[9px] px-1 py-px bg-green/10 text-green">SUCCESS</span>
          </div>
        </div>
      </div>

      {/* Log feed */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto font-mono text-xs"
        style={{ minHeight: 0 }}
      >
        {visible.length === 0 && (
          <div className="px-4 py-3 text-muted font-mono text-xs">Initializing pipeline…</div>
        )}
        {visible.map((entry, i) => (
          <LogLine key={i} entry={entry} />
        ))}
        {/* Blinking cursor */}
        <div className="flex items-center gap-3 px-4 py-1.5">
          <span className="font-mono text-[10px] text-muted w-20" />
          <span className="font-mono text-[10px] text-muted w-8" />
          <span className="font-mono text-[10px] text-muted w-20" />
          <span className={`font-mono text-[11px] text-signal-blue transition-opacity duration-75 ${cursor ? 'opacity-100' : 'opacity-0'}`}>
            █
          </span>
        </div>
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-border px-4 py-2 bg-panel flex items-center justify-between">
        <div className="flex gap-4">
          <span className="font-mono text-[10px] text-muted">
            <span className="text-text">74.4%</span> recovery
          </span>
          <span className="font-mono text-[10px] text-muted">
            <span className="text-signal-blue">+15.4%</span> vs Smart-Dunning
          </span>
          <span className="font-mono text-[10px] text-muted">
            <span className="text-green">0.0%</span> UIR
          </span>
        </div>
        <span className="font-mono text-[10px] text-muted">Phase 4+5 · seeds 1–10</span>
      </div>
    </div>
  )
}
