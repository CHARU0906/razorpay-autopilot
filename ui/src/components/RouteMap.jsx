/**
 * RouteMap — Checkpoint 1: static layout + three visual states.
 * No animation yet. previewState controls which sim_hour to render.
 *
 * Props:
 *   simHour      {number}  current simulated hour (drives state)
 *   onNodeClick  {fn}      called with route object on node click
 *   selectedId   {string}  currently selected node id
 */
import React from 'react'
import { ROUTES, HUB, CX, CY, routeState } from '../data/routeData.js'

const NODE_R   = 18    // normal node radius
const HUB_R    = 10    // hub radius
const COLORS   = {
  healthy:  '#5B8DEF',
  degrading: '#F5A623',
  detected:  '#E5484D',
  healthy_bg: '#141B26',
  muted:     '#6B7A90',
  text:      '#E8ECF1',
  border:    '#1E2A3A',
}

// Edge stroke width interpolation: 1.5px (healthy) → 0.6px (full incident)
function edgeWidth(degradation = 0) {
  return (1.5 - degradation * 0.9).toFixed(2)
}

function NodeCircle({ route, rs, isSelected, onClick }) {
  const isHealthy   = rs.state === 'healthy'
  const isDegrading = rs.state === 'degrading'
  const isDetected  = rs.state === 'detected'

  const borderColor = isHealthy
    ? COLORS.healthy
    : rs.color

  const fillColor = isDetected
    ? `${COLORS.detected}14`    // 8% opacity red fill
    : COLORS.healthy_bg

  const borderWidth = isDetected ? 2 : 1

  return (
    <g
      className="cursor-pointer"
      onClick={() => onClick(route)}
      role="button"
      aria-label={route.label}
    >
      {/* Selection ring */}
      {isSelected && (
        <circle
          cx={route.x} cy={route.y}
          r={NODE_R + 6}
          fill="none"
          stroke={borderColor}
          strokeWidth="1"
          strokeOpacity="0.4"
          strokeDasharray="3 2"
        />
      )}

      {/* Detection ring — static snapshot shows ring at full expansion */}
      {isDetected && (
        <circle
          cx={route.x} cy={route.y}
          r={NODE_R + 16}
          fill="none"
          stroke={COLORS.detected}
          strokeWidth="1"
          strokeOpacity="0.25"
        />
      )}

      {/* Main node circle */}
      <circle
        cx={route.x} cy={route.y}
        r={NODE_R}
        fill={fillColor}
        stroke={borderColor}
        strokeWidth={borderWidth}
      />

      {/* Degradation fill arc (shows how far into incident) */}
      {(isDegrading || isDetected) && rs.progress > 0 && (
        <circle
          cx={route.x} cy={route.y}
          r={NODE_R - 3}
          fill={`${rs.color}20`}
          stroke="none"
        />
      )}

      {/* INC label badge */}
      {route.sublabel && (isDetected || isDegrading) && (
        <text
          x={route.x + NODE_R + 4}
          y={route.y - NODE_R + 2}
          fontFamily="IBM Plex Mono, monospace"
          fontSize="8"
          fill={rs.color}
          fontWeight="600"
        >
          ● {route.sublabel}
        </text>
      )}

      {/* Node label */}
      <text
        x={route.x}
        y={route.y + NODE_R + 13}
        textAnchor="middle"
        fontFamily="IBM Plex Mono, monospace"
        fontSize="8.5"
        fill={isHealthy ? COLORS.muted : rs.color}
        letterSpacing="0.02em"
      >
        {route.label}
      </text>

      {/* Success rate for incident nodes */}
      {(isDegrading || isDetected) && (
        <text
          x={route.x}
          y={route.y + 4}
          textAnchor="middle"
          fontFamily="IBM Plex Mono, monospace"
          fontSize="9"
          fontWeight="600"
          fill={rs.color}
        >
          {(rs.currentRate * 100).toFixed(0)}%
        </text>
      )}

      {/* Healthy nodes: show small checkmark-style indicator */}
      {isHealthy && (
        <text
          x={route.x}
          y={route.y + 3.5}
          textAnchor="middle"
          fontFamily="IBM Plex Mono, monospace"
          fontSize="9"
          fill={`${COLORS.healthy}70`}
        >
          ✓
        </text>
      )}
    </g>
  )
}

function Edge({ route, rs }) {
  const isHealthy = rs.state === 'healthy'
  const strokeColor = isHealthy ? COLORS.healthy : rs.color
  const strokeOpacity = isHealthy ? 0.3 : 0.6
  const strokeWidth = isHealthy ? 1.5 : edgeWidth(rs.degradation || 0)

  return (
    <line
      x1={HUB.x} y1={HUB.y}
      x2={route.x} y2={route.y}
      stroke={strokeColor}
      strokeWidth={strokeWidth}
      strokeOpacity={strokeOpacity}
    />
  )
}

// Static preview controls — lets us show the three states side by side
const PREVIEW_HOURS = {
  healthy:   0,       // before any incident
  degrading: 247,     // INC-1 at step 2 (9h in, 87% → amber)
  detected:  250,     // INC-1 past detection latency (10h in, ~85%)
}

export default function RouteMap({ simHour = 0, onNodeClick = () => {}, selectedId = null }) {
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
          <div className="w-1.5 h-1.5 rounded-full bg-signal-blue" />
          <span className="font-sans text-xs font-medium text-muted uppercase tracking-wider">
            Payment Route Network
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ background: COLORS.healthy }} />
            <span className="font-mono text-[10px] text-muted">healthy</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ background: COLORS.degrading }} />
            <span className="font-mono text-[10px] text-muted">degrading</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ background: COLORS.detected }} />
            <span className="font-mono text-[10px] text-muted">incident detected</span>
          </div>
          <span className="font-mono text-[10px] text-muted">
            sim_h <span className="text-text">{simHour.toFixed(0)}</span>
          </span>
        </div>
      </div>

      {/* SVG canvas — flex-1 fills exact remaining height, preserveAspectRatio centers content */}
      <div
        className="flex-1"
        style={{ position: 'relative', minHeight: 0, overflow: 'hidden' }}
      >
        <svg
          viewBox="0 0 800 580"
          preserveAspectRatio="xMidYMid meet"
          style={{ width: '100%', height: '100%', display: 'block' }}
        >
          {/* Subtle grid backdrop */}
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1E2A3A" strokeWidth="0.5" strokeOpacity="0.4"/>
            </pattern>
          </defs>
          <rect width="800" height="580" fill="url(#grid)" />

          {/* Edges — drawn before nodes so nodes sit on top */}
          {ROUTES.map(route => {
            const rs = routeState(route, simHour)
            return <Edge key={`edge-${route.id}`} route={route} rs={rs} />
          })}

          {/* Hub */}
          <circle cx={HUB.x} cy={HUB.y} r={HUB_R} fill="#1E2A3A" stroke="#2E3D52" strokeWidth="1" />
          <text
            x={HUB.x} y={HUB.y + HUB_R + 12}
            textAnchor="middle"
            fontFamily="IBM Plex Mono, monospace"
            fontSize="8"
            fill={COLORS.muted}
          >
            GATEWAY
          </text>

          {/* Nodes */}
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
