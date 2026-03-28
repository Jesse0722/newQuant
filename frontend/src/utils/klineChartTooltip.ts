import type { QuoteItem } from '../types'

function fmtPrice(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(2)
}

function seriesDataText(data: unknown): string {
  if (data == null) return '—'
  if (typeof data === 'object' && data !== null && 'value' in data) {
    const v = (data as { value: unknown }).value
    if (v == null || Number.isNaN(Number(v))) return '—'
    return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  if (typeof data === 'number') {
    if (Number.isNaN(data)) return '—'
    return data.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  return String(data)
}

function resolvePctChg(quotes: QuoteItem[], dataIndex: number): number | null {
  const q = quotes[dataIndex]
  if (q?.pct_chg != null && !Number.isNaN(Number(q.pct_chg))) {
    return Number(q.pct_chg)
  }
  if (dataIndex > 0 && quotes[dataIndex - 1]) {
    const prevClose = quotes[dataIndex - 1].close
    const close = q?.close
    if (prevClose != null && close != null && prevClose !== 0) {
      return ((close - prevClose) / prevClose) * 100
    }
  }
  return null
}

/**
 * ECharts axis 型 tooltip：在 K 线 OHLC 下方展示当日涨幅（与行情 pct_chg 一致，缺失时用昨收推算）
 */
export function makeKlineAxisTooltipFormatter(quotes: QuoteItem[]) {
  return (params: unknown): string => {
    const ps = params as Array<{
      axisValue?: string
      axisValueLabel?: string
      dataIndex: number
      seriesName: string
      data: unknown
      marker?: string
    }>
    if (!Array.isArray(ps) || ps.length === 0) return ''
    const idx = ps[0].dataIndex
    const title = ps[0].axisValueLabel ?? ps[0].axisValue ?? ''
    const lines: string[] = [`<div style="font-weight:600;margin-bottom:6px">${title}</div>`]

    for (const p of ps) {
      const marker = p.marker ?? ''
      const name = p.seriesName
      if (name === 'K线' && Array.isArray(p.data) && p.data.length >= 4) {
        const [open, close, low, high] = p.data as number[]
        lines.push(`${marker}<span style="font-weight:500">${name}</span>`)
        lines.push(
          `开盘: ${fmtPrice(open)}　收盘: ${fmtPrice(close)}　最低: ${fmtPrice(low)}　最高: ${fmtPrice(high)}`
        )
        const pct = resolvePctChg(quotes, idx)
        if (pct != null) {
          const c = pct >= 0 ? '#cf1322' : '#3f8600'
          lines.push(
            `涨幅: <span style="color:${c};font-weight:600">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span>`
          )
        } else {
          lines.push('涨幅: —')
        }
        continue
      }
      lines.push(`${marker}${name}: ${seriesDataText(p.data)}`)
    }

    return lines.join('<br/>')
  }
}
