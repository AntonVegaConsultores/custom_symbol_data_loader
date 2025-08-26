# custom_symbol_data_loader

Lightweight QuantConnect helper package to ingest custom Forex quote (bid/ask) and trade (OHLC) CSV data from the ObjectStore, plot it, and apply a fill model that prices orders off imported quotes instead of live feed prices.

## 1. Overview

Provides:

- PythonData classes for EURUSD (fixed) and generic multi‑symbol Forex (deriving file names from alias and resolution).
- ImportedQuoteFillModel: fills market & limit orders using last imported QuoteBar bid/ask.
- ChartManager: creates charts (candlesticks, bid, ask, trades, spread) per alias prefix.
- Example algorithm (`MainAlgo` in `main.py` or `ExampleCustomDataAlgorithm` in `algorithm_example.py`).
- Simple assertion tests (no pytest) and optional inline local tests.

## 2. Motivation

Avoid duplication every time custom CSVs are imported into LEAN. Centralize parsing, plotting and consistent fill pricing. Now supports multiple time granularities via explicit filenames.

## 3. Installation

Copy the `custom_symbol_data_loader` folder (and optionally `main.py`) into your QuantConnect project root. No external dependencies required.

## 4. Quick Start

```python
from custom_symbol_data_loader import (
    CustomEurUsdQuoteData,
    TradingViewEurUsdTradeData,
    GenericForexQuoteData,
    GenericTradingViewForexTradeData,
    ImportedQuoteFillModel,
    ChartManager,
)

class MyAlgo(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2025, 7, 5)
        self.set_end_date(2025, 7, 15)
        self.set_cash(100000)

        # Ensure files exist in ObjectStore (upload manually or download once)
        # EURUSD mandatory (1min UTC by default)
        if not self.object_store.contains_key(CustomEurUsdQuoteData.KEY):
            self.object_store.save(CustomEurUsdQuoteData.KEY, self.download(CustomEurUsdQuoteData.KEY))
        if not self.object_store.contains_key(TradingViewEurUsdTradeData.KEY):
            self.object_store.save(TradingViewEurUsdTradeData.KEY, self.download(TradingViewEurUsdTradeData.KEY))

        # Add custom data (alias suffix can force granularity: _5MIN, _1H, _1D)
        self._alias = "EURUSD_IMPORT_5MIN"  # or simply "EURUSD_IMPORT"
        self._quotes = self.add_data(CustomEurUsdQuoteData, self._alias)
        self._trades = self.add_data(TradingViewEurUsdTradeData, self._alias)

        # Live symbol for orders + custom fill model
        fx = self.add_forex("EURUSD")
        fx.set_fee_model(ConstantFeeModel(0))
        self.securities[fx.symbol].set_fill_model(ImportedQuoteFillModel(self))

        # Charts
        self._charts = ChartManager(self)
        self._charts.setup_charts(self._alias)

    def on_data(self, slice):
        q_sym = getattr(self._quotes, 'symbol', None)
        q_bar = slice.quote_bars.get(q_sym) if q_sym else None
        if q_bar:
            self._last_import_quote = q_bar  # used by fill model
```

## 5. CSV File Structures

New explicit ObjectStore filename convention:

- Pattern: `fx-<PAIR>-<kind>-<granularity>-<tz>[-<source>].csv`
- kind: `quotes` (bid/ask) or `trades` (OHLC)
- granularity: `1s`, `1min`, `5min`, `15min`, `30min`, `1h`, `4h`, `1d`
- tz: usually `utc`
- source: optional, e.g. `tradingview`

Examples:

- Quotes (EURUSD, 1min): `fx-EURUSD-quotes-1min-utc.csv`
- Trades (EURUSD, 1min, TradingView): `fx-EURUSD-trades-1min-utc-tradingview.csv`
- Quotes (GBPUSD, 5min): `fx-GBPUSD-quotes-5min-utc.csv`

CSV contents remain the same as before:

Quote file (bid/ask):

```text
Date,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose,Volume
2025-07-10 00:00:00,1.17376,1.17377,1.17353,1.17359,1.17387,1.17388,1.17363,1.17369,278
```

TradingView trades:

```text
time,open,high,low,close,Volume
1751836440,1.17777,1.17796,1.17777,1.17796,1
```

## 6. Multi‑granularity support

- By default, the loader infers granularity from the subscription `config.increment` (resolution) and/or alias suffix.
- You can force granularity by appending `_<gran>` to the alias: `EURUSD_IMPORT_5MIN`, `GBPUSD_IMPORT_1H`, `USDJPY_IMPORT_1D`.
- Supported tokens: `1S`, `1MIN`, `5MIN`, `15MIN`, `30MIN`, `1H`, `4H`, `1D` (case‑insensitive). They map to filenames `1s`, `1min`, `5min`, `15min`, `30min`, `1h`, `4h`, `1d`.

## 7. Example Algorithm

See `main.py` (class `MainAlgo`) or `custom_symbol_data_loader/algorithm_example.py`.

## 8. Testing Strategy

- Plain `assert` scripts in `tests/` (`run_all_tests.py` aggregator) – no pytest dependency.
- Inline optional local tests in `main.py` guarded by `RUN_LOCAL_TESTS` flag.

## 9. Migration from old filenames

Old names used in earlier examples:

- Quotes: `EUR_USD.csv`, `GBP_USD.csv`
- Trades: `FX_EURUSD, 1.csv`, `FX_GBPUSD, 1.csv`

New names (1min examples):

- Quotes: `fx-EURUSD-quotes-1min-utc.csv`
- Trades: `fx-EURUSD-trades-1min-utc-tradingview.csv`

You can keep multiple granularities uploaded simultaneously, e.g. also
`fx-EURUSD-quotes-5min-utc.csv` for 5‑minute quotes. Select via alias suffix or resolution.

## 10. Public API

Exported via `custom_symbol_data_loader.__init__`:

- `CustomEurUsdQuoteData`
- `TradingViewEurUsdTradeData`
- `GenericForexQuoteData`
- `GenericTradingViewForexTradeData`
- `ImportedQuoteFillModel`
- `ChartManager`

## 11. Version

`__version__ = "0.1.0"`

## 12. License

Internal / unspecified. Add a license section if distributing.

---
End of README.
