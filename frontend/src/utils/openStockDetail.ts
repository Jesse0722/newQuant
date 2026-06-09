export const stockDetailPath = (tsCode: string) => `/stocks/${encodeURIComponent(tsCode)}`

export const openStockDetail = (tsCode: string) => {
  window.open(stockDetailPath(tsCode), '_blank', 'noopener,noreferrer')
}
