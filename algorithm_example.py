"""Example algorithm demonstrating custom multi-symbol Forex data usage.

Notes for QuantConnect Cloud:
  - Place the main algorithm class in main.py. Copy ExampleCustomDataAlgorithm
    into main.py or rename this file when uploading.
"""
from datetime import timedelta

try:  # Import QC classes when running in LEAN; fallback simple stubs locally
    from AlgorithmImports import (
        QCAlgorithm,
        Resolution,
        TimeZones,
        BrokerageName,
        AccountType,
        ConstantFeeModel,
        TradeBar,
    )
except Exception:  # minimal stubs for offline linting
    class QCAlgorithm: ...
    class Resolution: MINUTE = 1
    class TimeZones: UTC = None
    class BrokerageName: FXCM_BROKERAGE = None
    class AccountType: MARGIN = None
    class ConstantFeeModel:
        def __init__(self, v): ...
    class TradeBar: ...

from .data_sources import (
    CustomEurUsdQuoteData,
    TradingViewEurUsdTradeData,
    GenericForexQuoteData,
    GenericTradingViewForexTradeData,
    format_fx_filename,
)
from .fills import ImportedQuoteFillModel
from .charting import ChartManager


class ExampleCustomDataAlgorithm(QCAlgorithm):
    """Loads imported EURUSD (required) plus optional GBPUSD if files exist.

    Market + limit test orders executed once using ImportedQuoteFillModel.
    """
    ENABLE_GBPUSD = True  # set False to force single-symbol

    def initialize(self):
        self.set_start_date(2025, 7, 5)
        self.set_end_date(2025, 7, 15)
        self.set_cash(100000)

        # Ensure EURUSD files are present (download if needed)
        if not self.object_store.contains_key(CustomEurUsdQuoteData.KEY):
            self.object_store.save(CustomEurUsdQuoteData.KEY, self.download(CustomEurUsdQuoteData.KEY))
        if not self.object_store.contains_key(TradingViewEurUsdTradeData.KEY):
            self.object_store.save(TradingViewEurUsdTradeData.KEY, self.download(TradingViewEurUsdTradeData.KEY))

        # Add EURUSD custom data under alias.
        # To request other granularities, you can use alias suffixes like
        #   EURUSD_IMPORT_5MIN, EURUSD_IMPORT_1H, EURUSD_IMPORT_1D
        self._eurusd_alias = "EURUSD_IMPORT"
        self._eurusd_quotes = self.add_data(CustomEurUsdQuoteData, self._eurusd_alias, Resolution.MINUTE, time_zone=TimeZones.UTC, fill_forward=False)
        self._eurusd_trades = self.add_data(TradingViewEurUsdTradeData, self._eurusd_alias, Resolution.MINUTE, time_zone=TimeZones.UTC, fill_forward=False)

        # Optional GBPUSD if its files exist (default granularity 1min)
        self._gbpusd_enabled = False
        gbp_quote_key = format_fx_filename("GBPUSD", "quotes", "1min", "utc")
        gbp_trade_key = format_fx_filename("GBPUSD", "trades", "1min", "utc", source="tradingview")
        if self.ENABLE_GBPUSD and self.object_store.contains_key(gbp_quote_key) and self.object_store.contains_key(gbp_trade_key):
            self._gbpusd_alias = "GBPUSD_IMPORT"
            self._gbp_quotes = self.add_data(GenericForexQuoteData, self._gbpusd_alias, Resolution.MINUTE, time_zone=TimeZones.UTC, fill_forward=False)
            self._gbp_trades = self.add_data(GenericTradingViewForexTradeData, self._gbpusd_alias, Resolution.MINUTE, time_zone=TimeZones.UTC, fill_forward=False)
            self._gbpusd_enabled = True
        elif self.ENABLE_GBPUSD:
            self.debug("GBPUSD files not found; running EURUSD only.")

        # Live EURUSD for orders
        live = self.add_forex("EURUSD", Resolution.MINUTE)
        live.set_fee_model(ConstantFeeModel(0))
        self.set_brokerage_model(BrokerageName.FXCM_BROKERAGE, AccountType.MARGIN)
        self.securities[live.symbol].set_fill_model(ImportedQuoteFillModel(self))
        self._live_symbol = live.symbol

        # Charts
        self._chart_mgr = ChartManager(self)
        self._chart_mgr.setup_charts(self._eurusd_alias)
        if self._gbpusd_enabled:
            self._chart_mgr.setup_charts(self._gbpusd_alias)

        # Order flags
        self._eurusd_market_done = False
        self._eurusd_limit_done = False

    def _extract_tradebar(self, slice, symbol, tv_type):
        tb = slice.bars.get(symbol)
        if tb: return tb
        try:
            tv_dict = slice.Get(tv_type)
        except Exception:
            tv_dict = None
        if not tv_dict:
            return None
        raw = tv_dict.get(symbol)
        if raw is None:
            return None
        if isinstance(raw, TradeBar):
            return raw
        tb = TradeBar()
        tb.symbol = symbol
        tb.time = getattr(raw, 'time', self.time)
        tb.end_time = getattr(raw, 'end_time', tb.time + timedelta(minutes=1))
        tb.period = getattr(raw, 'period', timedelta(minutes=1))
        base = float(getattr(raw, 'open', getattr(raw, 'value', 0.0)))
        tb.open = base
        tb.high = float(getattr(raw, 'high', base))
        tb.low = float(getattr(raw, 'low', base))
        tb.close = float(getattr(raw, 'close', base))
        tb.volume = int(getattr(raw, 'volume', 0))
        return tb

    def on_data(self, slice):
        # EURUSD
        q_sym = getattr(self._eurusd_quotes, 'symbol', None)
        t_sym = getattr(self._eurusd_trades, 'symbol', None)
        q_bar = slice.quote_bars.get(q_sym) if q_sym else None
        t_bar = self._extract_tradebar(slice, t_sym, TradingViewEurUsdTradeData)
        if q_bar: self._last_import_quote = q_bar
        if q_bar or t_bar:
            self._chart_mgr.plot_data(self._eurusd_alias, q_bar, t_bar)

        if q_bar and t_bar and not self.is_warming_up:
            if not self._eurusd_market_done:
                self.market_order(self._live_symbol, 1000)
                self._eurusd_market_done = True
            if not self._eurusd_limit_done and getattr(q_bar, 'bid', None):
                self.limit_order(self._live_symbol, -1000, float(q_bar.bid.close))
                self._eurusd_limit_done = True

        # GBPUSD optional
        if self._gbpusd_enabled:
            gq_sym = getattr(self._gbp_quotes, 'symbol', None)
            gt_sym = getattr(self._gbp_trades, 'symbol', None)
            gq_bar = slice.quote_bars.get(gq_sym) if gq_sym else None
            gt_bar = self._extract_tradebar(slice, gt_sym, GenericTradingViewForexTradeData)
            if gq_bar or gt_bar:
                self._chart_mgr.plot_data(self._gbpusd_alias, gq_bar, gt_bar)
