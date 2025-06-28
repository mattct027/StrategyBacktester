from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import yfinance as yf
import pandas as pd

app = FastAPI()

# Allow CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/backtest/ma-crossover")
def ma_crossover_backtest(
    start: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end: str = Query(..., description="End date in YYYY-MM-DD format"),
    ma_20: int = Query(20, description="First MA window (default 20)"),
    ma_50: int = Query(50, description="Second MA window (default 50)"),
    ma_type: str = Query('sma', description="Type of moving average: 'sma' or 'ema'"),
    interval: str = Query('1h', description="Timeframe: 15m, 30m, 1h")
):
    # Validate interval
    valid_intervals = ['15m', '30m', '1h']
    if interval not in valid_intervals:
        return {"error": f"Invalid interval. Must be one of: {valid_intervals}"}
    
    # Calculate how much extra data we need for MA calculation
    max_ma_period = max(ma_20, ma_50)
    
    # Convert start date to datetime and subtract extra periods
    start_dt = pd.to_datetime(start)
    
    # For different intervals, calculate the appropriate lookback period
    if interval == '15m':
        # 15m intervals - need max_ma_period * 15 minutes back
        lookback_hours = max_ma_period * 0.25
    elif interval == '30m':
        # 30m intervals - need max_ma_period * 30 minutes back
        lookback_hours = max_ma_period * 0.5
    elif interval == '1h':
        # 1h intervals - need max_ma_period hours back
        lookback_hours = max_ma_period
    else:
        lookback_hours = max_ma_period
    
    # Calculate the actual start date for data fetching (with extra lookback)
    data_start = start_dt - pd.Timedelta(hours=lookback_hours)
    
    # Download data for Nasdaq futures (NQ=F) with extended lookback period
    df = yf.download("NQ=F", start=data_start, end=end, interval=interval)
    if df.empty:
        return {"error": "No data found for given period."}

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    # Convert index to US/Eastern timezone (New York time)
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert('America/New_York')
    else:
        df.index = df.index.tz_convert('America/New_York')

    # Make start_dt timezone-aware to match the DataFrame index
    if start_dt.tzinfo is None:
        start_dt = start_dt.tz_localize('America/New_York')
    else:
        start_dt = start_dt.tz_convert('America/New_York')

    # Check for required columns before proceeding
    required_cols = ['Close', 'Open']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        return {"error": f"Missing columns in data: {missing_cols}. Data returned: {list(df.columns)}"}

    if len(df) < max(ma_20, ma_50):
        return {"error": f"Not enough data for the selected MA windows. Only {len(df)} data points available."}

    # Calculate moving averages (SMA or EMA)
    if ma_type.lower() == 'ema':
        df['ma_20'] = df['Close'].ewm(span=ma_20, adjust=False).mean()
        df['ma_50'] = df['Close'].ewm(span=ma_50, adjust=False).mean()
    else:
        df['ma_20'] = df['Close'].rolling(window=ma_20).mean()
        df['ma_50'] = df['Close'].rolling(window=ma_50).mean()

    # Drop rows with NaNs in required columns
    try:
        df = df.dropna(subset=['ma_20', 'ma_50', 'Close', 'Open'])
    except KeyError as e:
        return {"error": f"KeyError during dropna: {e}. Data columns: {list(df.columns)}"}
    if df.empty:
        return {"error": "Not enough valid data after calculating moving averages."}

    # Filter to only return data from the requested start date onwards
    df = df[df.index >= start_dt]

    # Generate signals: 1 for long (20 over 50), -1 for short (20 under 50), 0 for no position
    df['signal'] = 0
    df.loc[df['ma_20'] > df['ma_50'], 'signal'] = 1
    df.loc[df['ma_20'] < df['ma_50'], 'signal'] = -1
    df['position_change'] = df['signal'].diff().fillna(0)

    # Find crossover events (entry on open of next bar)
    crossovers = []
    for i in range(1, len(df) - 1):
        prev_signal = df.iloc[i-1]['signal']
        curr_signal = df.iloc[i]['signal']
        if prev_signal != curr_signal:
            if curr_signal == 1:
                crossovers.append({
                    "entry_time": str(df.index[i+1]),
                    "type": "long",
                    "ma_20": df.iloc[i]['ma_20'],
                    "ma_50": df.iloc[i]['ma_50'],
                    "entry_open": df.iloc[i+1]['Open'],
                    "prev_close": df.iloc[i]['Close']
                })
            elif curr_signal == -1:
                crossovers.append({
                    "entry_time": str(df.index[i+1]),
                    "type": "short",
                    "ma_20": df.iloc[i]['ma_20'],
                    "ma_50": df.iloc[i]['ma_50'],
                    "entry_open": df.iloc[i+1]['Open'],
                    "prev_close": df.iloc[i]['Close']
                })

    df = df.reset_index()
    datetime_col = 'index' if 'index' in df.columns else df.columns[0]

    return {
        "datetime": df[datetime_col].astype(str).tolist(),
        "open": df['Open'].tolist(),
        "close": df['Close'].tolist(),
        "ma_20": df['ma_20'].tolist(),
        "ma_50": df['ma_50'].tolist(),
        "signal": df['signal'].tolist(),
        "crossovers": crossovers,
        "ma_type": ma_type.lower(),
        "interval": interval
    } 