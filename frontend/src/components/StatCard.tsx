import React, { useEffect, useRef, useState } from 'react'

interface StatCardProps {
  title: string
  value: number | string
  unit?: string
  icon?: React.ReactNode
  trend?: 'up' | 'down' | 'neutral'
  trendValue?: string
  accentColor?: string
  delay?: number
}

const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  unit,
  icon,
  trend,
  trendValue,
  accentColor = 'var(--accent)',
  delay = 0,
}) => {
  const [displayed, setDisplayed] = useState<number | string>(typeof value === 'number' ? 0 : value)
  const frameRef = useRef<number | null>(null)
  const startRef = useRef<number | null>(null)
  const duration = 800

  useEffect(() => {
    if (typeof value !== 'number') {
      setDisplayed(value)
      return
    }
    const target = value
    const start = () => {
      startRef.current = null
      const animate = (timestamp: number) => {
        if (!startRef.current) startRef.current = timestamp
        const elapsed = timestamp - startRef.current
        const progress = Math.min(elapsed / duration, 1)
        // easeOutCubic
        const eased = 1 - Math.pow(1 - progress, 3)
        setDisplayed(Math.round(eased * target))
        if (progress < 1) frameRef.current = requestAnimationFrame(animate)
      }
      frameRef.current = requestAnimationFrame(animate)
    }
    const timer = setTimeout(start, delay)
    return () => {
      clearTimeout(timer)
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [value, delay])

  const trendColor =
    trend === 'up' ? 'var(--color-up)' :
    trend === 'down' ? 'var(--color-down)' :
    'var(--text-muted)'

  return (
    <div
      className="glow-card fade-in-up"
      style={{
        padding: '20px 24px',
        cursor: 'default',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Accent gradient top border */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 2,
        background: `linear-gradient(90deg, ${accentColor}, transparent)`,
      }} />

      {/* Background glow */}
      <div style={{
        position: 'absolute', top: -20, right: -20, width: 100, height: 100,
        borderRadius: '50%',
        background: `radial-gradient(circle, ${accentColor}18 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
          {title}
        </span>
        {icon && (
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: `${accentColor}18`,
            border: `1px solid ${accentColor}30`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: accentColor, fontSize: 16,
          }}>
            {icon}
          </div>
        )}
      </div>

      {/* Value */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span className="mono count-anim" style={{
          fontSize: 36, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1,
        }}>
          {displayed}
        </span>
        {unit && (
          <span style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 500 }}>
            {unit}
          </span>
        )}
      </div>

      {/* Trend */}
      {trend && trendValue && (
        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            fontSize: 11, color: trendColor, fontWeight: 600,
            padding: '2px 8px', borderRadius: 20,
            background: trend === 'up' ? 'var(--color-up-dim)' : trend === 'down' ? 'var(--color-down-dim)' : 'rgba(255,255,255,0.05)',
          }}>
            {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '—'} {trendValue}
          </span>
        </div>
      )}
    </div>
  )
}

export default StatCard
