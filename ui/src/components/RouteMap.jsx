import React from 'react'
import { ROUTES, HUB, routeState } from '../data/routeData.js'

const NODE_R   = 20    // normal node radius
const HUB_R    = 10    // hub radius
const COLORS   = {
  healthy:    '#10B981', // Emerald green
  degrading:  '#F5A623', // Amber
  detected:   '#E5484D', // Crimson red
  healthy_bg: '#0F291E', // Dark emerald
  degrade_bg: '#2A1F0D', // Dark amber
  detect_bg:  '#311317', // Dark crimson
  muted:      '#8B9BB4',
  text:       '#E8ECF1',
  border:     '#1E2A3A',
}

// Edge stroke width interpolation
function edgeWidth(degradation = 0) {
  return (1.5 - degradation * 0.9).toFixed(2)
}

function AnimatedEdgePulse({ route, rs, index }) {
  const isHealthy  = rs.state === 'healthy'
  const pulseColor = isHealthy ? COLORS.healthy : rs.color
  const speed      = isHealthy ? 1.2 : rs.state === 'degrading' ? 1.8 : 2.5

  return (
    <g>
      <circle r={isHealthy ? "3" : "3.5"} fill={pulseColor} opacity="0.85">
        <animateMotion
          path={`M ${HUB.x} ${HUB.y} L ${route.x} ${route.y}`}
          dur={`${speed}s`}
          repeatCount="indefinite"
        />
      </circle>
      <circle r="1.5" fill="#FFFFFF" opacity="0.95">
        <animateMotion
          path={`M ${HUB.x} ${HUB.y} L ${route.x} ${route.y}`}
          dur={`${speed}s`}
          repeatCount="indefinite"
        />
      </circle>
    </g>
  )
}

function NodeCircle({ route, rs, isSelected, onClick }) {
  const isHealthy   = rs.state === 'healthy'
  const isDegrading = rs.state === 'degrading'
  const isDetected  = rs.state === 'detected'

  const borderColor = isHealthy ? COLORS.healthy : rs.color
  const fillColor   = isDetected ? COLORS.detect_bg : isDegrading ? COLORS.degrade_bg : COLORS.healthy_bg
  const borderWidth = isDetected ? 2.5 : isDegrading ? 2 : 1.5

  return (
    <g
      className="cursor-pointer group select-none"
      onClick={() => onClick(route)}
      role="button"
      aria-label={route.label}
    >
      {/* Selection halo */}
      {isSelected && (
        <circle
          cx={route.x} cy={route.y}
          r={NODE_R + 7}
          fill="none"
          stroke="#5B8DEF"
          strokeWidth="2"
          strokeOpacity="0.9"
          strokeDasharray="4 2"
        />
      )}

      {/* Detection animated radar ping ring */}
      {isDetected && (
        <circle
          cx={route.x} cy={route.y}
          r={NODE_R + 14}
          fill="none"
          stroke={COLORS.detected}
          strokeWidth="2"
          strokeOpacity="0.6"
          className="animate-ping"
          style={{ transformOrigin: `${route.x}px ${route.y}px` }}
        />
      )}

      {/* Main node background */}
      <circle
        cx={route.x} cy={route.y}
        r={NODE_R}
        fill={fillColor}
        stroke={borderColor}
        strokeWidth={borderWidth}
        style={{
          filter: isDetected
            ? 'drop-shadow(0 0 8px rgba(229, 72, 77, 0.6))'
            : isDegrading
            ? 'drop-shadow(0 0 6px rgba(245, 166, 35, 0.4))'
            : 'drop-shadow(0 0 4px rgba(16, 185, 129, 0.25))',
        }}
      />

      {/* Degradation fill arc */}
      {(isDegrading || isDetected) && rs.progress > 0 && (
        <circle
          cx={route.x} cy={route.y}
          r={NODE_R - 3}
          fill={`${rs.color}33`}
          stroke="none"
        />
      )}

      {/* Status badge pill above node */}
      {isDetected ? (
        <g transform={`translate(${route.x - 38}, ${route.y - NODE_R - 14})`}>
          <rect width="76" height="13" rx="3" fill="#E5484D" fillOpacity="0.25" stroke="#E5484D" strokeWidth="0.75" />
          <text x="38" y="9.5" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="7.5" fontWeight="700" fill="#FF8080">
            🚨 {route.sublabel || 'INCIDENT'}
          </text>
        </g>
      ) : isDegrading ? (
        <g transform={`translate(${route.x - 38}, ${route.y - NODE_R - 14})`}>
          <rect width="76" height="13" rx="3" fill="#F5A623" fillOpacity="0.25" stroke="#F5A623" strokeWidth="0.75" />
          <text x="38" y="9.5" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="7.5" fontWeight="700" fill="#F5A623">
            ⚠ DEGRADING
          </text>
        </g>
      ) : (
        <g transform={`translate(${route.x - 30}, ${route.y - NODE_R - 14})`}>
          <rect width="60" height="13" rx="3" fill="#10B981" fillOpacity="0.15" stroke="#10B981" strokeWidth="0.5" />
          <text x="30" y="9.5" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="7.5" fontWeight="600" fill="#34D399">
            ✓ HEALTHY
          </text>
        </g>
      )}

      {/* Success rate inside circle */}
      <text
        x={route.x}
        y={route.y + 3.5}
        textAnchor="middle"
        fontFamily="IBM Plex Mono, monospace"
        fontSize="9.5"
        fontWeight="700"
        fill={isDetected ? '#FF8080' : isDegrading ? '#F5A623' : '#34D399'}
      >
        {(rs.currentRate * 100).toFixed(0)}%
      </text>

      {/* Node label under circle */}
      <text
        x={route.x}
        y={route.y + NODE_R + 14}
        textAnchor="middle"
        fontFamily="IBM Plex Mono, monospace"
        fontSize="9"
        fontWeight="600"
        fill={isDetected ? '#FFA0A0' : isDegrading ? '#FCD34D' : '#D1D5DB'}
        letterSpacing="0.02em"
      >
        {route.label}
      </text>
    </g>
  )
}

function Edge({ route, rs }) {
  const isHealthy     = rs.state === 'healthy'
  const strokeColor   = isHealthy ? COLORS.healthy : rs.color
  const strokeOpacity = isHealthy ? 0.35 : 0.75
  const strokeWidth   = isHealthy ? 1.5 : edgeWidth(rs.degradation || 0)

  return (
    <line
      x1={HUB.x}
      y1={HUB.y}
      x2={route.x}
      y2={route.y}
      stroke={strokeColor}
      strokeWidth={strokeWidth}
      strokeOpacity={strokeOpacity}
      strokeDasharray={rs.state === 'degrading' ? '6 3' : rs.state === 'detected' ? '4 2' : 'none'}
    />
  )
}

export default function RouteMap({ simHour = 0, isPlaying = false, onNodeClick = () => {}, selectedId = null }) {
  // Compute counts for HUD summary
  const states = ROUTES.map(r => routeState(r, simHour))
  const healthyCount  = states.filter(s => s.state === 'healthy').length
  const degradingCount = states.filter(s => s.state === 'degrading').length
  const detectedCount  = states.filter(s => s.state === 'detected').length

  return (
    <div
      className="flex flex-col"
      style={{ background: '#0A0E14', width: '100%', height: '100%', overflow: 'hidden' }}
    >
      {/* Panel header */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0"
        style={{ background: '#141B26' }}
      >
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${isPlaying ? 'bg-green animate-pulse' : 'bg-signal-blue'}`} />
          <span className="font-sans text-xs font-medium text-muted uppercase tracking-wider">
            Payment Route Network {isPlaying && <span className="text-amber-300 text-[10px] ml-1">(SIM CLOCK RUNNING)</span>}
          </span>
        </div>

        {/* Live Cohort Status HUD */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-950/40">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span className="font-mono text-[10px] text-emerald-300 font-semibold">{healthyCount} Healthy</span>
          </div>
          {degradingCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-amber-500/40 bg-amber-950/40 animate-pulse">
              <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span className="font-mono text-[10px] text-amber-300 font-semibold">{degradingCount} Degrading</span>
            </div>
          )}
          {detectedCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-red-500/60 bg-red-950/50 shadow-sm shadow-red-900/50">
              <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-ping" />
              <span className="font-mono text-[10px] text-red-300 font-bold">{detectedCount} Incident Detected</span>
            </div>
          )}
          <span className="font-mono text-[10px] text-muted ml-2">
            sim_h <span className="text-signal-blue font-semibold">{simHour.toFixed(1)}</span>
          </span>
        </div>
      </div>

      {/* SVG canvas */}
      <div
        className="flex-1"
        style={{ position: 'relative', minHeight: 0, overflow: 'hidden' }}
      >
        <svg
          viewBox="0 0 800 580"
          preserveAspectRatio="xMidYMid meet"
          style={{ width: '100%', height: '100%', display: 'block' }}
        >
          {/* Grid backdrop */}
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1E2A3A" strokeWidth="0.5" strokeOpacity="0.4"/>
            </pattern>
          </defs>
          <rect width="800" height="580" fill="url(#grid)" />

          {/* Edges */}
          {ROUTES.map(route => {
            const rs = routeState(route, simHour)
            return <Edge key={route.id} route={route} rs={rs} />
          })}

          {/* Animated Edge Pulses */}
          {isPlaying && ROUTES.map((route, i) => {
            const rs = routeState(route, simHour)
            return <AnimatedEdgePulse key={route.id} route={route} rs={rs} index={i} />
          })}

          {/* Central Hub */}
          <g>
            <circle
              cx={HUB.x}
              cy={HUB.y}
              r={HUB_R + 8}
              fill="#5B8DEF15"
              stroke="#5B8DEF"
              strokeWidth="1"
              strokeOpacity="0.6"
            />
            <circle
              cx={HUB.x}
              cy={HUB.y}
              r={HUB_R}
              fill="#141B26"
              stroke="#5B8DEF"
              strokeWidth="2"
            />
            <text
              x={HUB.x}
              y={HUB.y + 3.5}
              textAnchor="middle"
              fontFamily="IBM Plex Mono, monospace"
              fontSize="7.5"
              fontWeight="700"
              fill="#5B8DEF"
            >
              HUB
            </text>
            <text
              x={HUB.x}
              y={HUB.y + 24}
              textAnchor="middle"
              fontFamily="IBM Plex Mono, monospace"
              fontSize="8.5"
              fontWeight="600"
              fill="#8B9BB4"
            >
              Razorpay Gateway
            </text>
          </g>

          {/* Peripheral Route Nodes */}
          {ROUTES.map(route => {
            const rs = routeState(route, simHour)
            return (
              <NodeCircle
                key={route.id}
                route={route}
                rs={rs}
                isSelected={selectedId === route.id}
                onClick={onNodeClick}
              />
            )
          })}
        </svg>
      </div>
    </div>
  )
}
