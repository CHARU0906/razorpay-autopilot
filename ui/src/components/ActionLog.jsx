import React, { useState, useEffect, useRef } from 'react'
import { TRACE_LOG_ENTRIES } from '../data/episodeData.js'

// Stage color map — amber/red only for gated states
const STAGE_STYLE = {
  investigator: { label: 'INV', color: 'text-signal-blue',  bg: 'bg-signal-blue/10' },
  strategist:   { label: 'STR', color: 'text-signal-blue',  bg: 'bg-signal-blue/10' },
  policy: {
    automatic: { label: 'POL', color: 'text-muted',   bg: 'bg-border/30' },
    approval:  { label: 'POL', color: 'text-amber',   bg: 'bg-amber/10'  },
    human:     { label: 'POL', color: 'text-red',     bg: 'bg-red/10'    },
  },
  action:   { label: 'ACT', color: 'text-text',         bg: 'bg-border/30' },
  outcome: {
    success:  { label: 'OUT', color: 'text-green',  bg: 'bg-green/10'  },
    failure:  { label: 'OUT', color: 'text-red',    bg: 'bg-red/10'    },
    approval: { label: 'OUT', color: 'text-amber',  bg: 'bg-amber/10'  },
  },
}

function getStyle(entry) {
  const s = STAGE_STYLE[entry.stage]
  if (!s) return { label: '???', color: 'text-muted', bg: 'bg-border/30' }
  if (entry.stage === 'policy') {
    return s[entry.tier] || s.automatic
  }
  if (entry.stage === 'outcome') {
    return s[entry.tier] || s.failure
  }
  return s
}

function LogLine({ entry, index }) {
  const style = getStyle(entry)
  const ts = entry.ts.slice(11, 23)  // HH:MM:SS.mmm

  return (
    <div className={`log-entry flex items-start gap-3 px-4 py-1.5 border-b border-border/30 hover:bg-panel/60 transition-colors`}>
      {/* Timestamp */}
      <span className="font-mono text-[10px] text-muted shrink-0 pt-px w-20">
        {ts}
      </span>
      {/* Stage badge */}
      <span className={`font-mono text-[10px] font-semibold shrink-0 px-1.5 py-0.5 ${style.color} ${style.bg} w-8 text-center`}>
        {style.label}
      </span>
      {/* Episode ID */}
      <span className="font-mono text-[10px] text-muted shrink-0 w-20 truncate">
        {entry.episode_id}
      </span>
      {/* Text */}
      <span className={`font-mono text-[11px] leading-relaxed ${style.color}`}>
        {entry.text}
      </span>
    </div>
  )
}

export default function ActionLog({ extraEntries = [] }) {
  const [visible, setVisible] = useState([])
  const [cursor, setCursor] = useState(true)
  const scrollRef = useRef(null)
  const timerRef = useRef(null)

  const allEntries = [...TRACE_LOG_ENTRIES, ...extraEntries]

  // Ticker: reveal one entry at a time, then loop
  useEffect(() => {
    let idx = 0
    const tick = () => {
      if (idx < allEntries.length) {
        setVisible(v => [...v, allEntries[idx]])
        idx++
        timerRef.current = setTimeout(tick, 260 + Math.random() * 180)
      } else {
        // Pause then restart
        timerRef.current = setTimeout(() => {
          setVisible([])
          idx = 0
          timerRef.current = setTimeout(tick, 400)
        }, 6000)
      }
    }
    timerRef.current = setTimeout(tick, 600)
    return () => clearTimeout(timerRef.current)
  }, [])

  // Blink cursor
  useEffect(() => {
    const iv = setInterval(() => setCursor(c => !c), 530)
    return () => clearInterval(iv)
  }, [])

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
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
          <div className="px-4 py-3 text-muted font-mono text-xs">
            Initializing pipeline…
          </div>
        )}
        {visible.map((entry, i) => (
          <LogLine key={`${entry.episode_id}-${i}`} entry={entry} index={i} />
        ))}
        {/* Cursor line */}
        <div className="flex items-center gap-3 px-4 py-1.5">
          <span className="font-mono text-[10px] text-muted w-20" />
          <span className="font-mono text-[10px] text-muted w-8" />
          <span className="font-mono text-[10px] text-muted w-20" />
          <span className={`font-mono text-[11px] text-signal-blue ${cursor ? 'opacity-100' : 'opacity-0'}`}>
            █
          </span>
        </div>
      </div>

      {/* Footer stats */}
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
        <span className="font-mono text-[10px] text-muted">
          Phase 4+5 · seeds 1–10
        </span>
      </div>
    </div>
  )
}
