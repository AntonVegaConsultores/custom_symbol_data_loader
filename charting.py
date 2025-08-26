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
    from AlgorithmImports import (CandlestickSeries, Chart, QCAlgorithm,
                                  QuoteBar, Series, SeriesType, TradeBar)
except Exception:  # stubs
    class QCAlgorithm: pass
    class QuoteBar: bid=None; ask=None
    class TradeBar: ...
    class Chart:
        def __init__(self, name): self.name=name
        def add_series(self, s):  # no-op stub for offline linting
            pass
    class CandlestickSeries:
        def __init__(self, name, unit): self.name=name
    class Series:
        def __init__(self, name, stype, unit): self.name=name
    class SeriesType: LINE=0

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

    def plot_data(self, prefix: str, quote_bar: Optional['QuoteBar'], trade_bar: Optional['TradeBar']) -> None:
        if quote_bar is not None:
            # Build a mid TradeBar aligned to the bar start (quote_bar.time)
            mid_tb = TradeBar()
            mid_tb.time = getattr(quote_bar, 'time', None)
            mid_tb.end_time = getattr(quote_bar, 'end_time', None)
            mid_tb.period = getattr(quote_bar, 'period', None)
            if getattr(quote_bar, 'bid', None) and getattr(quote_bar, 'ask', None):
                mid_tb.open = float((quote_bar.bid.open + quote_bar.ask.open) / 2.0)
                mid_tb.high = float((quote_bar.bid.high + quote_bar.ask.high) / 2.0)
                mid_tb.low = float((quote_bar.bid.low + quote_bar.ask.low) / 2.0)
                mid_tb.close = float((quote_bar.bid.close + quote_bar.ask.close) / 2.0)
            elif getattr(quote_bar, 'bid', None):
                mid_tb.open = float(quote_bar.bid.open)
                mid_tb.high = float(quote_bar.bid.high)
                mid_tb.low = float(quote_bar.bid.low)
                mid_tb.close = float(quote_bar.bid.close)
            elif getattr(quote_bar, 'ask', None):
                mid_tb.open = float(quote_bar.ask.open)
                mid_tb.high = float(quote_bar.ask.high)
                mid_tb.low = float(quote_bar.ask.low)
                mid_tb.close = float(quote_bar.ask.close)
            self.algorithm.plot(f"{prefix}_Quotes", "Quote_Mid", mid_tb)

            if getattr(quote_bar, 'bid', None):
                bid_tb = TradeBar()
                bid_tb.time = getattr(quote_bar, 'time', None)
                bid_tb.end_time = getattr(quote_bar, 'end_time', None)
                bid_tb.period = getattr(quote_bar, 'period', None)
                bid_tb.open = float(quote_bar.bid.open)
                bid_tb.high = float(quote_bar.bid.high)
                bid_tb.low = float(quote_bar.bid.low)
                bid_tb.close = float(quote_bar.bid.close)
                self.algorithm.plot(f"{prefix}_Bid", "Bid_OHLC", bid_tb)
            if getattr(quote_bar, 'ask', None):
                ask_tb = TradeBar()
                ask_tb.time = getattr(quote_bar, 'time', None)
                ask_tb.end_time = getattr(quote_bar, 'end_time', None)
                ask_tb.period = getattr(quote_bar, 'period', None)
                ask_tb.open = float(quote_bar.ask.open)
                ask_tb.high = float(quote_bar.ask.high)
                ask_tb.low = float(quote_bar.ask.low)
                ask_tb.close = float(quote_bar.ask.close)
                self.algorithm.plot(f"{prefix}_Ask", "Ask_OHLC", ask_tb)
            if getattr(quote_bar, 'bid', None) and getattr(quote_bar, 'ask', None):
                spread = quote_bar.ask.close - quote_bar.bid.close
                self.algorithm.plot(f"{prefix}_Spread", "Spread", spread)
        if trade_bar is not None:
            self.algorithm.plot(f"{prefix}_Trades", "Trade_OHLC", trade_bar)
