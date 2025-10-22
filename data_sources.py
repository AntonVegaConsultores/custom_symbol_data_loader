"""Custom data source classes for imported Forex quote and trade data.

Currently EURUSD-focused but extendable: duplicate a class and adjust KEY + docstring
for additional FX symbols (Option A multi-symbol strategy).

Example (algorithm initialize):
    from custom_symbol_data_loader import CustomEurUsdQuoteData, TradingViewEurUsdTradeData
  self.add_data(CustomEurUsdQuoteData, "EURUSD_IMPORT", Resolution.MINUTE)
  self.add_data(TradingViewEurUsdTradeData, "EURUSD_IMPORT", Resolution.MINUTE)

No external dependencies; uses only QuantConnect LEAN primitives.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Union

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

# ---- Global delta configuration ----
# A single global time delta applied to ALL readers in this module.
# Set it once from your algorithm if you need to shift timestamps uniformly.
_GLOBAL_DELTA: Optional[timedelta] = None

# Module-level simulated price deltas (applied to trade prices to create bid/ask)
# These defaults represent 1 pip for EURUSD (0.0001). They can be changed via
# the public setter `set_simulated_price_deltas`.
_SIMULATED_BID_DELTA: float = 0.0001
_SIMULATED_ASK_DELTA: float = 0.0001


def set_simulated_price_deltas(bid_delta: Optional[float] = None, ask_delta: Optional[float] = None) -> None:
    """Set module-wide simulated bid/ask deltas used by SimulatedEurUsdQuoteData.

    Pass None to leave a value unchanged. Values are floats representing
    absolute price offsets (e.g. 0.0001 for 1 pip on EURUSD).
    """
    global _SIMULATED_BID_DELTA, _SIMULATED_ASK_DELTA
    if bid_delta is not None:
        _SIMULATED_BID_DELTA = float(bid_delta)
    if ask_delta is not None:
        _SIMULATED_ASK_DELTA = float(ask_delta)

def _parse_delta_string(s: str) -> timedelta:
    """Parse a human-friendly delta string into timedelta.

    Examples: '30s', '5min', '2h', '1d', '+90s', '0.5h'.
    If the string is a plain number, it's treated as seconds.
    """
    s = s.strip().lower()
    # If it's just a number, interpret as seconds
    try:
        seconds = float(s)
        return timedelta(seconds=seconds)
    except Exception:
        pass
    # Extract number + unit
    m = re.match(r'^([+-]?\d+(?:\.\d*)?)\s*([a-z]+)$', s)
    if not m:
        raise ValueError("Invalid delta string. Use '30s', '5min', '2h', '1d' or raw seconds.")
    amount = float(m.group(1))
    unit = m.group(2)
    # Map synonyms to canonical unit keys
    synonyms = {
        's': 's', 'sec': 's', 'secs': 's', 'second': 's', 'seconds': 's',
        'm': 'min', 'min': 'min', 'mins': 'min', 'minute': 'min', 'minutes': 'min',
        'h': 'h', 'hr': 'h', 'hrs': 'h', 'hour': 'h', 'hours': 'h',
        'd': 'd', 'day': 'd', 'days': 'd',
    }
    canonical = synonyms.get(unit)
    if not canonical:
        raise ValueError("Unknown delta unit. Use s/sec, min, h/hr, or d/day.")
    field = {'s': 'seconds', 'min': 'minutes', 'h': 'hours', 'd': 'days'}[canonical]
    return timedelta(**{field: amount})

def set_global_delta(delta: Optional[Union[str, int, float, timedelta]]) -> None:
    """Define a global time offset applied by all readers in this module.

    Accepted values:
      - timedelta
      - number (seconds)
      - string with unit: 'Xs' seconds, 'Ymin' minutes, 'Zh' hours, 'Wd' days
      - None to clear
    """
    global _GLOBAL_DELTA
    # Inline parsing to keep this simple and obvious
    if delta is None:
        _GLOBAL_DELTA = None
        return
    if isinstance(delta, timedelta):
        _GLOBAL_DELTA = delta
        return
    if isinstance(delta, (int, float)):
        _GLOBAL_DELTA = timedelta(seconds=float(delta))
        return
    if isinstance(delta, str):
        _GLOBAL_DELTA = _parse_delta_string(delta)
        return
    raise ValueError("Unsupported delta type. Provide timedelta, number (seconds), or string like '5min'.")

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
            Old format (still supported):
                Date,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose,Volume

            New format (preferred):
                Date,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose,VolumeQuotes,Open,High,Low,Close,VolumeTrades

    Example line:
      2025-07-10 00:00:00,1.17376,1.17377,1.17353,1.17359,1.17387,1.17388,1.17363,1.17369,278

    Produces a QuoteBar with bid/ask Bar objects. If the new format is used,
        the trade OHLC (Open, High, Low, Close) columns will be parsed and we
        will attempt to set QuoteBar.open/high/low/close from them (supported in
        recent LEAN builds). We also set QuoteBar.value to the trade close. If
        direct assignment isn't supported by the runtime, the code falls back to
        keeping mid-derived values while still exposing trade close via value.

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
            
            # Apply global delta if set
            delta_time = _GLOBAL_DELTA
            if delta_time:
                time_obj = time_obj + delta_time
            
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
            qb.value = qb.close
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
    
    # Uses global delta only; no per-symbol overrides to keep it simple.

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
            
            # Apply global delta if set
            delta_time = _GLOBAL_DELTA
            if delta_time:
                time_obj = time_obj + delta_time
            
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


class SimulatedEurUsdQuoteData(PythonData):
    """Simulated EURUSD quote data from TradingView trade data.
    
    Reads OHLC trade data from TradingView format and generates bid/ask quotes
    by applying configurable deltas to the trade prices.
    
    CSV Format (same as TradingViewEurUsdTradeData):
      time,open,high,low,close,Volume
      
    Example line:
      1751836440,1.17777,1.17796,1.17777,1.17796,1
      
    Usage:
        # Configure module-level simulated deltas (e.g. 1 pip = 0.0001)
        set_simulated_price_deltas(bid_delta=0.0001, ask_delta=0.0001)
        # Then add the data source (no deltas passed to constructor)
        data_source = SimulatedEurUsdQuoteData()
        self.add_data(data_source, "EURUSD_IMPORT", Resolution.MINUTE)
    """
    
    # Default file for EURUSD trades at 1min UTC from TradingView
    KEY = format_fx_filename("EURUSD", "trades", "1min", "utc", source="tradingview")
    
    def __init__(self):
        """No per-instance deltas: reads module-level simulated deltas instead."""
        super().__init__()
    
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
            
            # Apply global delta if set
            delta_time = _GLOBAL_DELTA
            if delta_time:
                time_obj = time_obj + delta_time
            
            # Parse trade OHLC prices
            open_price = float(parts[1])
            high_price = float(parts[2])
            low_price = float(parts[3])
            close_price = float(parts[4])
            
            # Generate bid prices (subtract module-level bid delta)
            bid_open = open_price - _SIMULATED_BID_DELTA
            bid_high = high_price - _SIMULATED_BID_DELTA
            bid_low = low_price - _SIMULATED_BID_DELTA
            bid_close = close_price - _SIMULATED_BID_DELTA
            
            # Generate ask prices (add module-level ask delta)
            ask_open = open_price + _SIMULATED_ASK_DELTA
            ask_high = high_price + _SIMULATED_ASK_DELTA
            ask_low = low_price + _SIMULATED_ASK_DELTA
            ask_close = close_price + _SIMULATED_ASK_DELTA
            
            # Determine true period from alias/file granularity
            default_gran = _granularity_from_increment(getattr(config, 'increment', None))
            alias = getattr(config, 'symbol', None)
            sym_val = getattr(alias, 'value', str(alias))
            _pair, gran = _extract_pair_and_granularity(sym_val or "EURUSD", default_granularity=default_gran)
            period = _granularity_to_timedelta(gran)
            
            # Create QuoteBar with bid/ask data
            qb = QuoteBar()
            qb.symbol = config.symbol
            qb.time = time_obj
            qb.end_time = time_obj + period
            qb.period = period
            qb.bid = Bar(bid_open, bid_high, bid_low, bid_close)
            qb.ask = Bar(ask_open, ask_high, ask_low, ask_close)
            qb.value = qb.close
            return qb
        except Exception:
            return None


class GenericSimulatedTradingViewForexQuoteData(SimulatedEurUsdQuoteData):
    """Generic multi-symbol simulated TradingView quote data.

    Derives the ObjectStore key from the subscription symbol and granularity
    using pattern: fx-<PAIR>-trades-<gran>-utc-tradingview.csv and reuses the
    SimulatedEurUsdQuoteData reader to produce QuoteBar objects with
    simulated bid/ask prices.

    Usage:
        self.add_data(GenericSimulatedTradingViewForexQuoteData, "EURUSD_IMPORT", Resolution.MINUTE)
        self.add_data(GenericSimulatedTradingViewForexQuoteData, "GBPUSD_IMPORT_5MIN", Resolution.MINUTE)
    """

    # Inherit KEY from SimulatedEurUsdQuoteData; get_source will override

    def get_source(self, config: SubscriptionDataConfig, date: datetime, is_live_mode: bool) -> SubscriptionDataSource:
        default_gran = _granularity_from_increment(getattr(config, 'increment', None))
        pair, gran = _extract_pair_and_granularity(getattr(config.symbol, 'value', str(config.symbol)), default_granularity=default_gran)
        key = format_fx_filename(pair, "trades", gran, "utc", source="tradingview")
        return SubscriptionDataSource(key, SubscriptionTransportMedium.OBJECT_STORE)


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


class NewsDayState(PythonData):
    """Custom data loader for news day state CSV data.
    
    Loads data from news_day_state.csv with format:
    date,DayState
    2025-01-02 12:45:00,1
    2025-01-02 13:15:00,0
    2025-01-02 14:00:00,2
    
    DayState values: 0=OFF, 1=TURNING_OF, 2=FON
    """
    
    def get_source(self, config: SubscriptionDataConfig, date: datetime, is_live_mode: bool) -> SubscriptionDataSource:
        key = "news_day_state.csv"
        return SubscriptionDataSource(key, SubscriptionTransportMedium.OBJECT_STORE)
    
    def reader(self, config: SubscriptionDataConfig, line: str, date: datetime, is_live_mode: bool) -> BaseData:
        # Skip empty lines and header
        if not line.strip() or line.startswith('date'):
            return None
        
        try:
            # Parse: date,DayState
            data = line.split(',')
            if len(data) != 2:
                return None
            
            # Create new instance
            news_data = NewsDayState()
            news_data.symbol = config.symbol
            
            # Parse timestamp
            timestamp_str = data[0].strip()
            news_data.time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            news_data.end_time = news_data.time
            
            # Apply global delta if configured
            if _GLOBAL_DELTA is not None:
                news_data.time += _GLOBAL_DELTA
                news_data.end_time += _GLOBAL_DELTA
            
            # Parse DayState value
            day_state = int(data[1].strip())
            news_data.value = day_state
            news_data["DayState"] = day_state
            
            return news_data
            
        except Exception:
            # Skip malformed lines
            return None


class HolidayData(PythonData):
    """Custom data loader for holiday calendar dates.

    Expects an ObjectStore CSV named 'holidays.csv' with a single header column:
        holiday_date
        2025-01-09
        2025-01-20

    Each row yields a data point at 00:00:00 of the given date. The instance's
    value is set to 1 and an additional field 'HolidayDate' is included (ISO 'YYYY-MM-DD').
    If a global time delta is configured, it is applied ONLY to time/end_time.
    The 'HolidayDate' field always reflects the RAW CSV date (no delta applied).
    """

    def get_source(self, config: SubscriptionDataConfig, date: datetime, is_live_mode: bool) -> SubscriptionDataSource:
        key = "holidays.csv"
        return SubscriptionDataSource(key, SubscriptionTransportMedium.OBJECT_STORE)

    def reader(self, config: SubscriptionDataConfig, line: str, date: datetime, is_live_mode: bool) -> Optional[BaseData]:
        # Ignore empty lines and header
        if not line or not line.strip():
            return None
        if line.strip().lower().startswith("holiday_date"):
            return None

        try:
            # Accept potential extra columns, only first one matters (the date)
            parts = line.split(',')
            date_str = parts[0].strip()
            if not date_str:
                return None

            dt = datetime.strptime(date_str, "%Y-%m-%d")
            csv_date_str = dt.date().strftime("%Y-%m-%d")  # keep raw CSV date (no delta)

            item = HolidayData()
            item.symbol = config.symbol
            item.time = dt
            item.end_time = dt

            # Apply module-wide delta if set (time fields only, NOT HolidayDate)
            if _GLOBAL_DELTA is not None:
                item.time += _GLOBAL_DELTA
                item.end_time += _GLOBAL_DELTA

            # Emit a simple flag value and store the date explicitly (ISO string)
            item.value = 1
            item["HolidayDate"] = csv_date_str
            return item
        except Exception:
            return None
