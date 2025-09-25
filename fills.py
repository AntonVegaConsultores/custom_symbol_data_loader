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
    from AlgorithmImports import (FillModel, LimitIfTouchedOrder, LimitOrder,
                                  MarketOnCloseOrder, MarketOnOpenOrder,
                                  MarketOrder, Order, OrderDirection,
                                  OrderStatus, QuoteBar, Security,
                                  StopLimitOrder, StopMarketOrder,
                                  TrailingStopOrder)
except Exception:  # minimal stubs
    class FillModel:  # type: ignore
        def market_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def limit_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def stop_market_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def trailing_stop_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def stop_limit_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def limit_if_touched_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def market_on_open_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def market_on_close_fill(self, asset, order):
            class F: fill_price=0; status=None
            return F()
        def combo_market_fill(self, order, parameters):
            return []
        def combo_limit_fill(self, order, parameters):
            return []
        def combo_leg_limit_fill(self, order, parameters):
            return []
    class QuoteBar: bid=None; ask=None
    class OrderStatus: FILLED=1; NONE=0
    class OrderDirection: BUY=0; SELL=1
    class MarketOrder: direction=None
    class LimitOrder: direction=None; limit_price=0
    class StopMarketOrder: direction=None; stop_price=0
    class TrailingStopOrder: direction=None; stop_price=0
    class StopLimitOrder: direction=None; stop_price=0; limit_price=0
    class LimitIfTouchedOrder: direction=None; trigger_price=0; limit_price=0
    class MarketOnOpenOrder: direction=None
    class MarketOnCloseOrder: direction=None
    class Order: pass
    class Security: price=0

class ImportedQuoteFillModel(FillModel):
    """FillModel that prices fills off the most recent imported QuoteBar.

    Expects algorithm to set self._last_import_quote with a QuoteBar containing
    bid/ask. If missing falls back to Security.price for market orders and no
    fill for limits.
    """
    def __init__(self, algorithm, symbol):
        super().__init__()
        self.algorithm = algorithm
        self.symbol = symbol

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

    def stop_market_fill(self, asset: 'Security', order: 'StopMarketOrder'):
        """Price stop orders off the latest imported QuoteBar.

        Trigger rules:
        - BUY stop (closing a short): triggers when ask.close >= stop
          Fill at max(ask.close, stop)
        - SELL stop (closing a long): triggers when bid.close <= stop
          Fill at min(bid.close, stop)
        Fallback: if no quote available, use asset.price and default behavior.
        """
        fill = super().stop_market_fill(asset, order)
        qb = self._get_last_import_quote()
        if qb is None or qb.bid is None or qb.ask is None:
            # Fallback to Security.price heuristic
            price = float(getattr(asset, 'price', 0.0) or 0.0)
            stop_price = getattr(order, 'stop_price', getattr(order, 'StopPrice', None))
            if stop_price is None:
                return fill  # cannot determine; leave as default
            # Simple default trigger check mirroring Lean's semantics
            if order.direction == OrderDirection.BUY and price >= float(stop_price):
                fill.fill_price = price
                fill.status = OrderStatus.FILLED
            elif order.direction == OrderDirection.SELL and price <= float(stop_price):
                fill.fill_price = price
                fill.status = OrderStatus.FILLED
            return fill

        stop_price = getattr(order, 'stop_price', getattr(order, 'StopPrice', None))
        if stop_price is None:
            return fill
        s = float(stop_price)

        if order.direction == OrderDirection.BUY:
            # Buy stop -> trigger when ask >= stop
            ask_c = float(qb.ask.close)
            if ask_c >= s:
                fill.fill_price = float(max(ask_c, s))
                fill.status = OrderStatus.FILLED
        else:
            # Sell stop -> trigger when bid <= stop
            bid_c = float(qb.bid.close)
            if bid_c <= s:
                fill.fill_price = float(min(bid_c, s))
                fill.status = OrderStatus.FILLED
        return fill

    # --- Additional order models -------------------------------------
    def trailing_stop_fill(self, asset: 'Security', order: 'TrailingStopOrder'):
        """Treat trailing stop similar to stop market using current StopPrice.

        Uses same trigger rules as StopMarketFill but reads stop price from the order.
        """
        # Reuse stop logic
        # Some runtimes expose StopPrice/stop_price
        stop_price = getattr(order, 'stop_price', getattr(order, 'StopPrice', None))
        # Build a temporary StopMarketOrder-like object to reuse logic
        class _Tmp:
            pass
        tmp = _Tmp()
        setattr(tmp, 'direction', getattr(order, 'direction', None))
        setattr(tmp, 'stop_price', stop_price)
        return self.stop_market_fill(asset, tmp)  # type: ignore[arg-type]

    def stop_limit_fill(self, asset: 'Security', order: 'StopLimitOrder'):
        """Stop-Limit: first trigger stop, then apply limit conditions using bid/ask.

        - BUY stop-limit: trigger when ask >= stop; fill only if ask <= limit at min(ask, limit)
        - SELL stop-limit: trigger when bid <= stop; fill only if bid >= limit at max(bid, limit)
        """
        fill = super().stop_limit_fill(asset, order)
        qb = self._get_last_import_quote()
        if qb is None or qb.bid is None or qb.ask is None:
            return fill
        stop = getattr(order, 'stop_price', getattr(order, 'StopPrice', None))
        limit = getattr(order, 'limit_price', getattr(order, 'LimitPrice', None))
        if stop is None or limit is None:
            return fill
        s = float(stop); l = float(limit)
        if order.direction == OrderDirection.BUY:
            ask_c = float(qb.ask.close)
            if ask_c >= s and ask_c <= l:
                fill.fill_price = float(min(ask_c, l))
                fill.status = OrderStatus.FILLED
        else:
            bid_c = float(qb.bid.close)
            if bid_c <= s and bid_c >= l:
                fill.fill_price = float(max(bid_c, l))
                fill.status = OrderStatus.FILLED
        return fill

    def limit_if_touched_fill(self, asset: 'Security', order: 'LimitIfTouchedOrder'):
        """Limit-If-Touched: trigger opposite to stop, then apply limit.

        - BUY LIT: trigger when ask <= trigger; fill if ask <= limit at min(ask, limit)
        - SELL LIT: trigger when bid >= trigger; fill if bid >= limit at max(bid, limit)
        """
        fill = super().limit_if_touched_fill(asset, order)
        qb = self._get_last_import_quote()
        if qb is None or qb.bid is None or qb.ask is None:
            return fill
        trigger = getattr(order, 'trigger_price', getattr(order, 'TriggerPrice', None))
        limit = getattr(order, 'limit_price', getattr(order, 'LimitPrice', None))
        if trigger is None or limit is None:
            return fill
        t = float(trigger); l = float(limit)
        if order.direction == OrderDirection.BUY:
            ask_c = float(qb.ask.close)
            if ask_c <= t and ask_c <= l:
                fill.fill_price = float(min(ask_c, l))
                fill.status = OrderStatus.FILLED
        else:
            bid_c = float(qb.bid.close)
            if bid_c >= t and bid_c >= l:
                fill.fill_price = float(max(bid_c, l))
                fill.status = OrderStatus.FILLED
        return fill

    def market_on_open_fill(self, asset: 'Security', order: 'MarketOnOpenOrder'):
        """Simple MOO: price like market using latest quote side."""
        fill = super().market_on_open_fill(asset, order)
        qb = self._get_last_import_quote()
        if qb is None or qb.bid is None or qb.ask is None:
            # fallback to asset price
            fill.fill_price = float(getattr(asset, 'price', 0.0) or 0.0)
            fill.status = OrderStatus.FILLED
            return fill
        if getattr(order, 'direction', None) == OrderDirection.BUY:
            fill.fill_price = float(qb.ask.close)
        else:
            fill.fill_price = float(qb.bid.close)
        fill.status = OrderStatus.FILLED
        return fill

    def market_on_close_fill(self, asset: 'Security', order: 'MarketOnCloseOrder'):
        """Simple MOC: price like market using latest quote side."""
        fill = super().market_on_close_fill(asset, order)
        qb = self._get_last_import_quote()
        if qb is None or qb.bid is None or qb.ask is None:
            fill.fill_price = float(getattr(asset, 'price', 0.0) or 0.0)
            fill.status = OrderStatus.FILLED
            return fill
        if getattr(order, 'direction', None) == OrderDirection.BUY:
            fill.fill_price = float(qb.ask.close)
        else:
            fill.fill_price = float(qb.bid.close)
        fill.status = OrderStatus.FILLED
        return fill

    # --- PascalCase wrappers for compatibility ------------------------
    # These redirect to the pythonic snake_case versions to ensure the
    # FillModelPythonWrapper can resolve overrides regardless of casing.
    def MarketFill(self, asset: 'Security', order: 'MarketOrder'):
        return self.market_fill(asset, order)
    def LimitFill(self, asset: 'Security', order: 'LimitOrder'):
        return self.limit_fill(asset, order)
    def StopMarketFill(self, asset: 'Security', order: 'StopMarketOrder'):
        return self.stop_market_fill(asset, order)
    def TrailingStopFill(self, asset: 'Security', order: 'TrailingStopOrder'):
        return self.trailing_stop_fill(asset, order)
    def StopLimitFill(self, asset: 'Security', order: 'StopLimitOrder'):
        return self.stop_limit_fill(asset, order)
    def LimitIfTouchedFill(self, asset: 'Security', order: 'LimitIfTouchedOrder'):
        return self.limit_if_touched_fill(asset, order)
    def MarketOnOpenFill(self, asset: 'Security', order: 'MarketOnOpenOrder'):
        return self.market_on_open_fill(asset, order)
    def MarketOnCloseFill(self, asset: 'Security', order: 'MarketOnCloseOrder'):
        return self.market_on_close_fill(asset, order)
    # Combo fills pass-through to base behavior
    def ComboMarketFill(self, order: 'Order', parameters):
        return super().combo_market_fill(order, parameters)
    def ComboLimitFill(self, order: 'Order', parameters):
        return super().combo_limit_fill(order, parameters)
    def ComboLegLimitFill(self, order: 'Order', parameters):
        return super().combo_leg_limit_fill(order, parameters)
