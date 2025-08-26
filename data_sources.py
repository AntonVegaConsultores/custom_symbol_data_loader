"""Custom data source classes for imported Forex quote and trade data.

Currently EURUSD-focused but extendable: duplicate a class and adjust KEY + docstring
for additional FX symbols (Option A multi-symbol strategy).

Example (algorithm initialize):
    from custom_symbol_data_loader import CustomEurUsdQuoteData, TradingViewEurUsdTradeData
  self.add_data(CustomEurUsdQuoteData, "EURUSD_IMPORT", Resolution.MINUTE)
  self.add_data(TradingViewEurUsdTradeData, "EURUSD_IMPORT", Resolution.MINUTE)

No external dependencies; uses only QuantConnect LEAN primitives.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import re

try:  # Safe imports for LEAN environment or local linting
    from AlgorithmImports import (Bar, BaseData, PythonData, QuoteBar,
                                  SubscriptionDataConfig,
                                  SubscriptionDataSource,
                                  SubscriptionTransportMedium, TradeBar)
except Exception:  # Minimal stubs
    class PythonData: ...
    class BaseData: ...
    class Bar:
        def __init__(self, o,h,l,c):
            self.open=o; self.high=h; self.low=l; self.close=c
    class QuoteBar:
        bid=None; ask=None
    class TradeBar: ...
    class SubscriptionDataConfig:
        increment=None; symbol=None
    class SubscriptionDataSource:
        def __init__(self, *a, **k): ...
    class SubscriptionTransportMedium:
        OBJECT_STORE = 0

# ---- Helpers for filename convention and parsing ----
# New explicit convention (ObjectStore key = file name):
#   fx-<PAIR>-<kind>-<granularity>-<tz>[-<source>].csv
# Examples:
#   fx-EURUSD-quotes-1min-utc.csv
#   fx-EURUSD-trades-1h-utc-tradingview.csv
#
# Granularity labels supported: 1s, 1min, 5min, 15min, 30min, 1h, 4h, 1d

_GRANULARITY_MAP_SECONDS = {
    1: "1s",
    60: "1min",
    300: "5min",
    900: "15min",
    1800: "30min",
    3600: "1h",
    14400: "4h",
    86400: "1d",
}

_VALID_GRANULARITIES = set(_GRANULARITY_MAP_SECONDS.values())


def format_fx_filename(pair: str, kind: str, granularity: str, tz: str = "utc", source: Optional[str] = None) -> str:
    """Builds an ObjectStore filename for FX data.

    pair: like 'EURUSD' (no separator)
    kind: 'quotes' (bid/ask) or 'trades' (OHLC)
    granularity: one of _VALID_GRANULARITIES
    tz: e.g. 'utc'
    source: optional suffix like 'tradingview'
    """
    pair = pair.upper()
    kind = kind.lower()
    granularity = granularity.lower()
    tz = tz.lower()
    if granularity not in _VALID_GRANULARITIES:
        raise ValueError(f"Unsupported granularity '{granularity}'")
    suffix = f"-{source.lower()}" if source else ""
    return f"fx-{pair}-{kind}-{granularity}-{tz}{suffix}.csv"


def _extract_pair_and_granularity(symbol_value: str, default_granularity: str = "1min") -> Tuple[str, str]:
    """Extract pair (first 6 letters) and granularity from alias like
    'EURUSD_IMPORT_5MIN' or 'GBPUSD_1H'. Falls back to default_granularity.
    """
    s = str(symbol_value).upper()
    pair = s[:6]
    # Look for trailing _<gran> (accept MIN/H/H/D variants)
    m = re.search(r"_(1S|1MIN|5MIN|15MIN|30MIN|1H|4H|1D)$", s)
    if m:
        token = m.group(1)
        token = token.lower()
        token = token.replace("min", "min")  # no-op for clarity
        gran = token
        # normalize like '1min' from '1min', etc.
        if gran not in _VALID_GRANULARITIES:
            gran = default_granularity
    else:
        gran = default_granularity
    return pair, gran


def _granularity_from_increment(inc: Optional[timedelta]) -> str:
    if not inc:
        return "1min"
    secs = int(inc.total_seconds())
    return _GRANULARITY_MAP_SECONDS.get(secs, "1min")


def _is_empty_line(line: str) -> bool:
    return (not line) or (line.strip()=="") or (not line[0].isdigit())


def _granularity_to_timedelta(gran: str) -> timedelta:
    g = gran.lower()
    if g == "1s":
        return timedelta(seconds=1)
    if g == "1min":
        return timedelta(minutes=1)
    if g == "5min":
        return timedelta(minutes=5)
    if g == "15min":
        return timedelta(minutes=15)
    if g == "30min":
        return timedelta(minutes=30)
    if g == "1h":
        return timedelta(hours=1)
    if g == "4h":
        return timedelta(hours=4)
    if g == "1d":
        return timedelta(days=1)
    # Fallback
    return timedelta(minutes=1)


class CustomEurUsdQuoteData(PythonData):
    """Custom EURUSD quote (bid/ask) data -> yields QuoteBar.

    CSV Format (ObjectStore file name KEY):
      Date,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose,Volume

    Example line:
      2025-07-10 00:00:00,1.17376,1.17377,1.17353,1.17359,1.17387,1.17388,1.17363,1.17369,278

    Produces a QuoteBar with bid/ask Bar objects. Mid prices (close etc.) are
    computed by LEAN from bid/ask (no manual assignment needed).

    Usage:
      self.add_data(CustomEurUsdQuoteData, "EURUSD_IMPORT", Resolution.MINUTE)

    Attributes:
      KEY (str): Default ObjectStore key for the CSV file (1min UTC).
    """
    # Default file for EURUSD quotes at 1min UTC
    KEY = format_fx_filename("EURUSD", "quotes", "1min", "utc")

    def get_source(self, config: SubscriptionDataConfig, date: datetime, is_live_mode: bool) -> SubscriptionDataSource:
        # Derive file name from symbol alias and requested increment
        default_gran = _granularity_from_increment(getattr(config, 'increment', None))
        alias = getattr(config, 'symbol', None)
        sym_val = getattr(alias, 'value', str(alias))
        pair, gran = _extract_pair_and_granularity(sym_val or "EURUSD", default_granularity=default_gran)
        key = format_fx_filename(pair, "quotes", gran, "utc")
        return SubscriptionDataSource(key, SubscriptionTransportMedium.OBJECT_STORE)

    def reader(self, config: SubscriptionDataConfig, line: str, date: datetime, is_live_mode: bool) -> Optional[BaseData]:
        if _is_empty_line(line):
            return None
        try:
            data = line.split(',')
            time_obj = datetime.strptime(data[0].strip(), "%Y-%m-%d %H:%M:%S")
            bid_open, bid_high, bid_low, bid_close = map(float, data[1:5])
            ask_open, ask_high, ask_low, ask_close = map(float, data[5:9])
            # Determine true period from alias/file granularity
            default_gran = _granularity_from_increment(getattr(config, 'increment', None))
            alias = getattr(config, 'symbol', None)
            sym_val = getattr(alias, 'value', str(alias))
            _pair, gran = _extract_pair_and_granularity(sym_val or "EURUSD", default_granularity=default_gran)
            period = _granularity_to_timedelta(gran)
            qb = QuoteBar()
            qb.symbol = config.symbol
            qb.time = time_obj
            qb.end_time = time_obj + period
            qb.period = period
            qb.bid = Bar(bid_open, bid_high, bid_low, bid_close)
            qb.ask = Bar(ask_open, ask_high, ask_low, ask_close)
            qb.value = qb.close  # close derived from mid
            return qb
        except Exception:
            return None


class TradingViewEurUsdTradeData(PythonData):
    """Custom EURUSD trade OHLC data (TradingView export) -> yields custom objects.

    CSV Format (KEY):
      time,open,high,low,close,Volume

    Example line:
      1751836440,1.17777,1.17796,1.17777,1.17796,1

    Yields instances of this same class (pattern recommended for PythonData) with
    attributes open/high/low/close/volume/value so they can be converted or plotted.

    Usage:
      self.add_data(TradingViewEurUsdTradeData, "EURUSD_IMPORT", Resolution.MINUTE)
    """
    # Default file for EURUSD trades at 1min UTC from TradingView
    KEY = format_fx_filename("EURUSD", "trades", "1min", "utc", source="tradingview")

    def get_source(self, config: SubscriptionDataConfig, date: datetime, is_live_mode: bool) -> SubscriptionDataSource:
        default_gran = _granularity_from_increment(getattr(config, 'increment', None))
        alias = getattr(config, 'symbol', None)
        sym_val = getattr(alias, 'value', str(alias))
        pair, gran = _extract_pair_and_granularity(sym_val or "EURUSD", default_granularity=default_gran)
        key = format_fx_filename(pair, "trades", gran, "utc", source="tradingview")
        return SubscriptionDataSource(key, SubscriptionTransportMedium.OBJECT_STORE)

    def reader(self, config: SubscriptionDataConfig, line: str, date: datetime, is_live_mode: bool) -> Optional[BaseData]:
        if _is_empty_line(line) or line.startswith("time"):
            return None
        try:
            parts = line.split(',')
            ts_raw = int(parts[0].strip())
            if ts_raw > 10**12:  # milliseconds
                ts_raw //= 1000
            time_obj = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            open_price = float(parts[1]); high_price = float(parts[2])
            low_price = float(parts[3]); close_price = float(parts[4])
            volume = int(parts[5])
            # Determine true period from alias/file granularity
            default_gran = _granularity_from_increment(getattr(config, 'increment', None))
            alias = getattr(config, 'symbol', None)
            sym_val = getattr(alias, 'value', str(alias))
            _pair, gran = _extract_pair_and_granularity(sym_val or "EURUSD", default_granularity=default_gran)
            period = _granularity_to_timedelta(gran)
            bar = TradingViewEurUsdTradeData()
            bar.symbol = config.symbol
            bar.time = time_obj
            bar.end_time = time_obj + period
            bar.period = period
            bar.open = open_price; bar.high = high_price
            bar.low = low_price; bar.close = close_price
            bar.volume = volume
            bar.value = close_price
            return bar
        except Exception:
            return None


class GenericForexQuoteData(CustomEurUsdQuoteData):
        """Generic multi-symbol Forex quote (bid/ask) data loader.

        Derives the ObjectStore key from the subscription symbol and requested
        granularity using pattern: fx-<PAIR>-quotes-<gran>-utc.csv

        To use for multiple symbols simultaneously:
            self.add_data(GenericForexQuoteData, "EURUSD_IMPORT", Resolution.MINUTE)
            self.add_data(GenericForexQuoteData, "GBPUSD_IMPORT_5MIN", Resolution.MINUTE)

        Requirements:
            - Upload files following the new naming, e.g. fx-EURUSD-quotes-1min-utc.csv,
              fx-GBPUSD-quotes-5min-utc.csv, etc.
            - Alias symbol value should start with 6 FX letters (e.g. EURUSD, GBPUSD) and
              can optionally end with _<gran> like _5MIN, _1H, _1D to force a granularity.
        """

        def get_source(self, config: SubscriptionDataConfig, date: datetime, is_live_mode: bool) -> SubscriptionDataSource:
                default_gran = _granularity_from_increment(getattr(config, 'increment', None))
                pair, gran = _extract_pair_and_granularity(getattr(config.symbol, 'value', str(config.symbol)), default_granularity=default_gran)
                key = format_fx_filename(pair, "quotes", gran, "utc")
                return SubscriptionDataSource(key, SubscriptionTransportMedium.OBJECT_STORE)


class GenericTradingViewForexTradeData(TradingViewEurUsdTradeData):
        """Generic multi-symbol TradingView OHLC Forex data loader.

        Derives the ObjectStore key from the subscription symbol and granularity
        using pattern: fx-<PAIR>-trades-<gran>-utc-tradingview.csv

        Example usage for two symbols:
            self.add_data(GenericTradingViewForexTradeData, "EURUSD_IMPORT", Resolution.MINUTE)
            self.add_data(GenericTradingViewForexTradeData, "GBPUSD_IMPORT_1H", Resolution.HOUR)

        Ensure corresponding files are uploaded.
        """

        def get_source(self, config: SubscriptionDataConfig, date: datetime, is_live_mode: bool) -> SubscriptionDataSource:
                default_gran = _granularity_from_increment(getattr(config, 'increment', None))
                pair, gran = _extract_pair_and_granularity(getattr(config.symbol, 'value', str(config.symbol)), default_granularity=default_gran)
                key = format_fx_filename(pair, "trades", gran, "utc", source="tradingview")
                return SubscriptionDataSource(key, SubscriptionTransportMedium.OBJECT_STORE)
