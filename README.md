# Strategy Backtester Backend

This is a simple FastAPI backend for backtesting a moving average crossover strategy on Nasdaq futures (NQ=F) using yfinance data.

## Features
- Fetches historical data for Nasdaq futures (15m, 30m, 1h timeframes)
- Runs a moving average crossover backtest (default: 20/50 MA)
- Returns PnL, price, and signal series for charting

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the server:**
   ```bash
   uvicorn main:app --reload
   ```

3. **API Endpoint:**
   - `GET /backtest/ma-crossover?start=YYYY-MM-DD&end=YYYY-MM-DD&short_window=20&long_window=50&interval=1h`
   - Example: `http://127.0.0.1:8000/backtest/ma-crossover?start=2024-04-01&end=2024-05-01&interval=1h`
   - Supported intervals: 15m, 30m, 1h

## Notes
- The backend is CORS-enabled for easy frontend integration.
- You can adjust the moving average windows via query parameters.
- Data availability limits: 15m (~7 days), 30m (~60 days), 1h (~2 years) from today. 