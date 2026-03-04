import client from './client'

export interface OcrExtractResult {
  raw_text: string
  parsed: {
    trade_date?: string
    trade_time?: string
    direction?: string
    price?: number
    quantity?: number
  }
  error?: string
}

export const extractTradeFromImage = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return client.post<OcrExtractResult>('/ocr/extract', form)
}
