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

function fmtIntLike(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function fmtAmountLike(n: number | null | undefined): string {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })
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
      // OHLC 必须以 quotes[dataIndex] 为准。ECharts 轴触发下 candlestick 的 params.data
      // 在部分版本/结构下可能为 { value: [...] }、维序不一致或与内部编码不一致，会导致开盘/高低与后端不符。
      if (name === 'K线') {
        const q = quotes[idx]
        if (!q) {
          lines.push(`${marker}<span style="font-weight:500">${name}</span>`)
          lines.push('暂无该日行情')
          continue
        }
        lines.push(`${marker}<span style="font-weight:500">${name}</span>`)
        lines.push(
          `开盘: ${fmtPrice(q.open)}　收盘: ${fmtPrice(q.close)}　最低: ${fmtPrice(q.low)}　最高: ${fmtPrice(q.high)}`
        )
        lines.push(
          `成交量: ${fmtIntLike(q.vol)}　成交额: ${fmtAmountLike(q.amount)}`
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
        const tr = q.turnover_rate
        if (tr != null && !Number.isNaN(Number(tr))) {
          lines.push(`换手率: ${Number(tr).toFixed(2)}%`)
        } else {
          lines.push('换手率: —')
        }
        continue
      }
      if (name === '成交量') {
        // 已在 K 线主信息中展示成交量，避免重复
        continue
      }
      lines.push(`${marker}${name}: ${seriesDataText(p.data)}`)
    }

    return lines.join('<br/>')
  }
}
