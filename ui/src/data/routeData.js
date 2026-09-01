/**
 * Route definitions for the network map.
 * Incident cohort keys match Phase 5 detector MONITORED_KEYS exactly.
 * Positions are fixed radial around a central hub — not force-directed.
 *
 * Hub center: (400, 300) in a 800×600 SVG viewport.
 * Peripheral radius: 240px.
 * 7 nodes placed at specific angles so the 3 incident nodes are
 * visually separated at 10-o'clock, 2-o'clock, and 6-o'clock.
 */

const CX = 400  // hub x
const CY = 290  // hub y (slightly above center for visual balance)
const R  = 230  // peripheral radius

// angle in degrees, 0 = right, clockwise
function polar(deg, r = R) {
  const rad = (deg - 90) * Math.PI / 180   // -90 so 0deg = top
  return { x: Math.round(CX + r * Math.cos(rad)), y: Math.round(CY + r * Math.sin(rad)) }
}

export const HUB = { id: 'hub', label: 'Razorpay\nGateway', ...polar(0, 0), isHub: true }

export const ROUTES = [
  // ── Incident cohorts (10 o'clock, 2 o'clock, 6 o'clock) ──────────────────
  {
    id: 'IN|rupay|HDFC',
    label: 'IN · rupay · HDFC',
    sublabel: 'INC-1',
    isIncident: true,
    incidentId: 'INC-1',
    ...polar(315),   // 10 o'clock
    // Real INC-1 trajectory from sim_config.yaml
    trajectory: [
      { offset_h: 0.0,  success_rate: 0.94 },
      { offset_h: 4.5,  success_rate: 0.91 },
      { offset_h: 9.0,  success_rate: 0.87 },
      { offset_h: 13.5, success_rate: 0.82 },
    ],
    window_h: 18,
    incident_start_h: 240,
    detection_latency_h: 7.5,    // mean from Phase 5 benchmark
    episodeCount: 80,
  },
  {
    id: 'xb|route_b',
    label: 'xb · route_b',
    sublabel: 'INC-2',
    isIncident: true,
    incidentId: 'INC-2',
    ...polar(45),    // 2 o'clock
    trajectory: [
      { offset_h: 0.0, success_rate: 0.96 },
      { offset_h: 4.0, success_rate: 0.90 },
      { offset_h: 8.0, success_rate: 0.84 },
    ],
    window_h: 12,
    incident_start_h: 300,
    detection_latency_h: 9.3,
    episodeCount: 80,
  },
  {
    id: 'upi|PAYTM',
    label: 'upi · PAYTM',
    sublabel: 'INC-3',
    isIncident: true,
    incidentId: 'INC-3',
    ...polar(180),   // 6 o'clock
    trajectory: [
      { offset_h: 0.0,  success_rate: 0.93 },
      { offset_h: 6.0,  success_rate: 0.89 },
      { offset_h: 12.0, success_rate: 0.85 },
      { offset_h: 18.0, success_rate: 0.88 },
    ],
    window_h: 24,
    incident_start_h: 360,
    detection_latency_h: 7.6,
    episodeCount: 80,
  },

  // ── Healthy routes (fill the gaps for baseline contrast) ─────────────────
  {
    id: 'IN|card|ICICI',
    label: 'IN · card · ICICI',
    sublabel: null,
    isIncident: false,
    ...polar(0),     // 3 o'clock
    episodeCount: 95,
  },
  {
    id: 'IN|visa|SBIN',
    label: 'IN · visa · SBIN',
    sublabel: null,
    isIncident: false,
    ...polar(90),    // 6 o'clock right (between INC-2 and INC-3)
    episodeCount: 110,
  },
  {
    id: 'IN|netbank|AXIS',
    label: 'IN · netbank · AXIS',
    sublabel: null,
    isIncident: false,
    ...polar(225),   // 7-8 o'clock (between INC-3 and INC-1)
    episodeCount: 88,
  },
  {
    id: 'upi|HDFC',
    label: 'upi · HDFC',
    sublabel: null,
    isIncident: false,
    ...polar(270),   // 9 o'clock
    episodeCount: 102,
  },
]

export { CX, CY }

/**
 * Compute visual state for a route given current sim_hour.
 *
 * Returns one of:
 *   { state: 'healthy', currentRate: 0.98, color: '#10B981', degradation: 0 }
 *   { state: 'degrading', progress: 0-1, currentRate: float, color: hex, degradation: float }
 *   { state: 'detected',  progress: 0-1, currentRate: float, color: hex, detectionFired: bool, degradation: float }
 */
export function routeState(route, simHour) {
  // Healthy baseline route default
  if (!route.isIncident) {
    return {
      state: 'healthy',
      currentRate: 0.98,
      color: '#10B981',
      progress: 0,
      detectionFired: false,
      degradation: 0,
    }
  }

  // Check if simulated hour is within or near the incident window
  const elapsed = simHour - route.incident_start_h

  // Multi-cohort demo contrast mode (when viewing INC-1 at h=240..260, show INC-2 in early degrading state for contrast)
  if (route.id === 'xb|route_b' && simHour >= 240 && simHour <= 260) {
    return {
      state: 'degrading',
      progress: 0.45,
      currentRate: 0.88,
      color: '#F5A623',
      detectionFired: false,
      degradation: 0.5,
      isDemoDegrading: true,
    }
  }

  if (elapsed < 0) {
    return {
      state: 'healthy',
      currentRate: 0.96,
      color: '#10B981',
      progress: 0,
      detectionFired: false,
      degradation: 0,
    }
  }
  
  if (elapsed >= route.window_h) {
    return {
      state: 'healthy',
      currentRate: 0.95,
      color: '#10B981',
      progress: 1,
      detectionFired: false,
      degradation: 0,
    }
  }

  const progress = Math.min(elapsed / route.window_h, 1)

  // Interpolate success rate from trajectory
  const traj = route.trajectory
  let currentRate = traj[0].success_rate
  for (let i = 0; i < traj.length - 1; i++) {
    const a = traj[i], b = traj[i + 1]
    if (elapsed >= a.offset_h && elapsed < b.offset_h) {
      const t = (elapsed - a.offset_h) / (b.offset_h - a.offset_h)
      currentRate = a.success_rate + t * (b.success_rate - a.success_rate)
      break
    }
    if (i === traj.length - 2 && elapsed >= b.offset_h) {
      currentRate = b.success_rate
    }
  }

  // Color: interpolate #10B981 → #F5A623 → #E5484D based on rate drop
  const HEALTHY_RATE = 0.94
  const FULL_RATE    = 0.82
  const degradation  = Math.max(0, Math.min(1,
    (HEALTHY_RATE - currentRate) / (HEALTHY_RATE - FULL_RATE)
  ))

  let color
  if (degradation < 0.4) {
    const t = degradation / 0.4
    color = lerpHex('#10B981', '#F5A623', t)
  } else {
    const t = (degradation - 0.4) / 0.6
    color = lerpHex('#F5A623', '#E5484D', t)
  }

  const detectionFired = elapsed >= route.detection_latency_h
  const state = detectionFired ? 'detected' : 'degrading'

  return { state, progress, currentRate, color, detectionFired, degradation }
}

function lerpHex(a, b, t) {
  const ar = parseInt(a.slice(1, 3), 16), ag = parseInt(a.slice(3, 5), 16), ab = parseInt(a.slice(5, 7), 16)
  const br = parseInt(b.slice(1, 3), 16), bg = parseInt(b.slice(3, 5), 16), bb = parseInt(b.slice(5, 7), 16)
  const r = Math.round(ar + (br - ar) * t)
  const g = Math.round(ag + (bg - ag) * t)
  const bv = Math.round(ab + (bb - ab) * t)
  return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${bv.toString(16).padStart(2,'0')}`
}
