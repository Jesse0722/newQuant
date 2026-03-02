import re

_TS_CODE_RE = re.compile(r"^\d{6}\.[A-Z]{2}$")

_PREFIX_TO_EXCHANGE = {
    "6": "SH",
    "0": "SZ",
    "3": "SZ",
    "8": "BJ",
    "4": "BJ",
}


def normalize_ts_code(code: str) -> str:
    """将股票代码标准化为 Tushare ts_code 格式（如 000001.SZ）。

    支持输入：
      - 纯数字: 000001 → 000001.SZ
      - 已有后缀: 000001.SZ → 000001.SZ（保持不变）
      - 带 sz/sh 前缀: sz000001 → 000001.SZ
    """
    code = code.strip().upper()

    if _TS_CODE_RE.match(code):
        return code

    for prefix in ("SZ", "SH", "BJ"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break

    code = re.sub(r"[^0-9]", "", code)

    if len(code) != 6:
        raise ValueError(f"无效的股票代码：{code}，应为6位数字")

    exchange = _PREFIX_TO_EXCHANGE.get(code[0])
    if not exchange:
        raise ValueError(f"无法识别交易所：代码 {code} 首位 '{code[0]}' 不在已知范围")

    return f"{code}.{exchange}"
