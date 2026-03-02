import pandas as pd
import numpy as np


def calc_ma(df: pd.DataFrame, n: int) -> pd.Series:
    return df["close"].rolling(n).mean()


def calc_ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def calc_macd(df: pd.DataFrame):
    ema12 = calc_ema(df["close"], 12)
    ema26 = calc_ema(df["close"], 26)
    dif = ema12 - ema26
    dea = calc_ema(dif, 9)
    histogram = (dif - dea) * 2
    return dif, dea, histogram


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_vol_ma(df: pd.DataFrame, n: int = 5) -> pd.Series:
    return df["vol"].rolling(n).mean()


def calc_n_day_high(df: pd.DataFrame, n: int) -> pd.Series:
    return df["close"].rolling(n).max()
