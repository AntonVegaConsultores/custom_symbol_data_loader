"""Custom FillModel leveraging imported QuoteBars (bid/ask) instead of live quotes.

Decision Flow (Market vs Limit):

 MarketOrder -> fetch last imported QuoteBar ->
   if missing: fallback asset.price -> fill
   else direction BUY? use ask.close : use bid.close -> fill

 LimitOrder -> fetch last imported QuoteBar ->
   if missing: no fill
   else if BUY and ask.close <= limit -> fill at min(ask.close, limit)
        if SELL and bid.close >= limit -> fill at max(bid.close, limit)
   else remain unfilled

Safe fallback logic keeps behavior predictable when custom data lags.
"""
from typing import Optional

try:
    from AlgorithmImports import (FillModel, LimitOrder, MarketOrder,
                                  OrderDirection, OrderStatus, QuoteBar,
                                  Security)
except Exception:  # minimal stubs
    class FillModel:  # type: ignore
        def market_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def limit_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
    class QuoteBar: bid=None; ask=None
    class OrderStatus: FILLED=1; NONE=0
    class OrderDirection: BUY=0; SELL=1
    class MarketOrder: direction=None
    class LimitOrder: direction=None; limit_price=0
    class Security: price=0

class ImportedQuoteFillModel(FillModel):
    """FillModel that prices fills off the most recent imported QuoteBar.

    Expects algorithm to set self._last_import_quote with a QuoteBar containing
    bid/ask. If missing falls back to Security.price for market orders and no
    fill for limits.
    """
    def __init__(self, algorithm):
        super().__init__()
        self.algorithm = algorithm

    def _get_last_import_quote(self) -> Optional[QuoteBar]:
        """Return last imported QuoteBar if algorithm stored it.

        Simplified (Step 9): removed unused secondary fallback path that
        introspected securities cache. The algorithm now sets
        self._last_import_quote explicitly in OnData after receiving custom
        quote data, making additional lookups unnecessary and reducing silent
        failure surfaces.
        """
        return getattr(self.algorithm, "_last_import_quote", None)

    def market_fill(self, asset: 'Security', order: 'MarketOrder'):
        fill = super().market_fill(asset, order)
        qb = self._get_last_import_quote()
        if qb is None or qb.bid is None or qb.ask is None:
            fill.fill_price = float(asset.price)
            fill.status = OrderStatus.FILLED
            return fill
        if order.direction == OrderDirection.BUY:
            fill.fill_price = float(qb.ask.close)
        else:
            fill.fill_price = float(qb.bid.close)
        fill.status = OrderStatus.FILLED
        return fill

    def limit_fill(self, asset: 'Security', order: 'LimitOrder'):
        fill = super().limit_fill(asset, order)
        qb = self._get_last_import_quote()
        if qb is None or qb.bid is None or qb.ask is None:
            fill.status = OrderStatus.NONE
            return fill
        if order.direction == OrderDirection.BUY:
            if qb.ask.close <= order.limit_price:
                fill.fill_price = float(min(qb.ask.close, order.limit_price))
                fill.status = OrderStatus.FILLED
        else:
            if qb.bid.close >= order.limit_price:
                fill.fill_price = float(max(qb.bid.close, order.limit_price))
                fill.status = OrderStatus.FILLED
        return fill
