"""Chart management helpers for plotting imported QuoteBars and Trade data.

Usage:
    from custom_symbol_data_loader import ChartManager
  self._chart_mgr = ChartManager(self)
  self._chart_mgr.setup_charts(prefix="EURUSD_IMPORT")
  ... in OnData:
      self._chart_mgr.plot_data(prefix, quote_bar, trade_bar)

Creates per-prefix charts:
  <prefix>_Quotes (candlestick mid)
  <prefix>_Bid (candlestick bid OHLC)
  <prefix>_Ask (candlestick ask OHLC)
  <prefix>_Trades (candlestick trade OHLC)
  <prefix>_Spread (line spread)
"""

from typing import Optional

try:
    from AlgorithmImports import (
        CandlestickSeries,
        Chart,
        QCAlgorithm,
        QuoteBar,
        Series,
        SeriesType,
        TradeBar,
    )
except Exception:  # stubs

    class QCAlgorithm:
        pass

    class QuoteBar:
        bid = None
        ask = None

    class TradeBar: ...

    class Chart:
        def __init__(self, name):
            self.name = name

        def add_series(self, s):  # no-op stub for offline linting
            pass

    class CandlestickSeries:
        def __init__(self, name, unit):
            self.name = name

    class Series:
        def __init__(self, name, stype, unit):
            self.name = name

    class SeriesType:
        LINE = 0


class ChartManager:
    def __init__(self, algorithm: QCAlgorithm):
        self.algorithm = algorithm

    def setup_charts(self, prefix: str = "EURUSD_Import") -> None:
        q_chart = Chart(f"{prefix}_Quotes")
        q_chart.add_series(CandlestickSeries("Quote_Mid", "$"))
        self.algorithm.add_chart(q_chart)

        b_chart = Chart(f"{prefix}_Bid")
        b_chart.add_series(CandlestickSeries("Bid_OHLC", "$"))
        self.algorithm.add_chart(b_chart)

        a_chart = Chart(f"{prefix}_Ask")
        a_chart.add_series(CandlestickSeries("Ask_OHLC", "$"))
        self.algorithm.add_chart(a_chart)

        t_chart = Chart(f"{prefix}_Trades")
        t_chart.add_series(CandlestickSeries("Trade_OHLC", "$"))
        self.algorithm.add_chart(t_chart)

        s_chart = Chart(f"{prefix}_Spread")
        s_chart.add_series(Series("Spread", SeriesType.LINE, "$"))
        self.algorithm.add_chart(s_chart)

    def plot_quote_data(self, prefix: str, quote_bar: Optional["QuoteBar"]) -> None:
        """Plot QuoteBar-derived visuals: mid (or embedded trade OHLC), bid, ask and spread."""
        if quote_bar is None:
            return
        # Build a mid TradeBar aligned to the bar start (quote_bar.time)
        mid_tb = TradeBar()
        mid_tb.time = getattr(quote_bar, "time", None)
        mid_tb.end_time = getattr(quote_bar, "end_time", None)
        mid_tb.period = getattr(quote_bar, "period", None)
        # Prefer trade OHLC embedded in QuoteBar if available (new format)
        q_open = getattr(quote_bar, "open", None)
        q_high = getattr(quote_bar, "high", None)
        q_low = getattr(quote_bar, "low", None)
        q_close = getattr(quote_bar, "close", None)
        if all(v is not None for v in (q_open, q_high, q_low, q_close)):
            mid_tb.open = float(q_open)
            mid_tb.high = float(q_high)
            mid_tb.low = float(q_low)
            mid_tb.close = float(q_close)
        self.algorithm.plot(f"{prefix}_Quotes", "Quote_Mid", mid_tb)

        if getattr(quote_bar, "bid", None):
            bid_tb = TradeBar()
            bid_tb.time = getattr(quote_bar, "time", None)
            bid_tb.end_time = getattr(quote_bar, "end_time", None)
            bid_tb.period = getattr(quote_bar, "period", None)
            bid_tb.open = float(quote_bar.bid.open)
            bid_tb.high = float(quote_bar.bid.high)
            bid_tb.low = float(quote_bar.bid.low)
            bid_tb.close = float(quote_bar.bid.close)
            self.algorithm.plot(f"{prefix}_Bid", "Bid_OHLC", bid_tb)
        if getattr(quote_bar, "ask", None):
            ask_tb = TradeBar()
            ask_tb.time = getattr(quote_bar, "time", None)
            ask_tb.end_time = getattr(quote_bar, "end_time", None)
            ask_tb.period = getattr(quote_bar, "period", None)
            ask_tb.open = float(quote_bar.ask.open)
            ask_tb.high = float(quote_bar.ask.high)
            ask_tb.low = float(quote_bar.ask.low)
            ask_tb.close = float(quote_bar.ask.close)
            self.algorithm.plot(f"{prefix}_Ask", "Ask_OHLC", ask_tb)
        if getattr(quote_bar, "bid", None) and getattr(quote_bar, "ask", None):
            spread = quote_bar.ask.close - quote_bar.bid.close
            self.algorithm.plot(f"{prefix}_Spread", "Spread", spread)

    def plot_trade_data(self, prefix: str, trade_bar: Optional["TradeBar"]) -> None:
        """Plot TradeBar (or custom trade data) as candlestick series."""
        if trade_bar is None:
            return
        # Ensure we pass a proper TradeBar object to candlestick series.
        if isinstance(trade_bar, TradeBar):
            tb = trade_bar
        else:
            tb = TradeBar()
            tb.time = getattr(trade_bar, "time", None)
            tb.end_time = getattr(trade_bar, "end_time", None)
            tb.period = getattr(trade_bar, "period", None)
            o = getattr(trade_bar, "open", None)
            h = getattr(trade_bar, "high", None)
            l = getattr(trade_bar, "low", None)
            c = getattr(trade_bar, "close", None)
            if None not in (o, h, l, c):
                tb.open = float(o)
                tb.high = float(h)
                tb.low = float(l)
                tb.close = float(c)
            v = getattr(trade_bar, "volume", None)
            if v is not None:
                try:
                    tb.volume = float(v)
                except Exception:
                    pass
        if all(hasattr(tb, attr) for attr in ("open", "high", "low", "close")):
            self.algorithm.plot(f"{prefix}_Trades", "Trade_OHLC", tb)

    def plot_data(
        self,
        prefix: str,
        quote_bar: Optional["QuoteBar"],
        trade_bar: Optional["TradeBar"],
    ) -> None:
        """Backward-compatible wrapper calling the separated plot methods."""
        self.plot_quote_data(prefix, quote_bar)
        self.plot_trade_data(prefix, trade_bar)
