from fastapi import APIRouter, UploadFile, File
from app.services.ocr_service import extract_text, parse_trade_from_text

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


@router.post("/extract")
async def extract_trade_from_image(file: UploadFile = File(...)):
    """上传券商成交截图，OCR 识别并解析交易字段。"""
    content = await file.read()
    try:
        raw_text = extract_text(content)
    except RuntimeError as e:
        return {"raw_text": "", "parsed": {}, "error": str(e)}
    parsed = parse_trade_from_text(raw_text)
    return {"raw_text": raw_text, "parsed": parsed}
