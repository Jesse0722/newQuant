import io
import re
from PIL import Image
import pytesseract


def extract_text(image_bytes: bytes) -> str:
    """使用 Tesseract OCR 从图片中提取文本。需安装 tesseract: brew install tesseract tesseract-lang"""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    try:
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return text.strip() if text else ""
    except pytesseract.pytesseract.TesseractNotFoundError:
        raise RuntimeError("未安装 Tesseract，请执行: brew install tesseract tesseract-lang")
    except Exception as e:
        raise RuntimeError(f"OCR 识别失败: {e}")


def parse_trade_from_text(text: str) -> dict:
    """
    从 OCR 文本中解析交易明细字段。
    支持常见券商截图格式，返回可空字段。
    """
    parsed: dict = {}
    text_clean = text.replace(" ", "").replace("\t", "")

    # 日期: 2024-03-01, 20240301, 2024/03/01
    date_match = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text_clean)
    if date_match:
        parsed["trade_date"] = f"{date_match.group(1)}{date_match.group(2)}{date_match.group(3)}"

    # 时间: 09:35, 09:35:00
    time_match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text_clean)
    if time_match:
        h, m = time_match.group(1).zfill(2), time_match.group(2)
        s = time_match.group(3) or "00"
        parsed["trade_time"] = f"{h}:{m}:{s}"

    # 方向: 买/卖/买入/卖出
    if re.search(r"买|买入", text_clean):
        parsed["direction"] = "buy"
    elif re.search(r"卖|卖出", text_clean):
        parsed["direction"] = "sell"

    # 成交价/价格: 成交价 10.50 或 成交价:10.50
    price_match = re.search(r"(?:成交价|价格|单价|委托价)[:：]?\s*([\d.]+)", text_clean)
    if not price_match:
        price_match = re.search(r"([\d]+\.\d{2})\s*元", text_clean)
    if price_match:
        try:
            parsed["price"] = float(price_match.group(1))
        except ValueError:
            pass

    # 数量: 数量 1000 或 数量:1000
    qty_match = re.search(r"(?:数量|股数|成交数量)[:：]?\s*(\d+)", text_clean)
    if not qty_match:
        qty_match = re.search(r"(\d+)\s*股", text_clean)
    if qty_match:
        try:
            parsed["quantity"] = int(qty_match.group(1))
        except ValueError:
            pass

    return parsed
