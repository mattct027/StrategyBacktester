import streamlit as st
import pandas as pd
import datetime
import yfinance as yf

st.title("NQ MA Crossover Backtester")

# Sidebar for user input
st.sidebar.header("Strategy Settings")
start_date = st.sidebar.date_input("Start Date", datetime.date(2024, 4, 1))
end_date = st.sidebar.date_input("End Date", datetime.date(2024, 5, 1))
ma_20 = st.sidebar.number_input("MA 1 Period (default 20)", min_value=1, value=20)
ma_50 = st.sidebar.number_input("MA 2 Period (default 50)", min_value=1, value=50)
ma_type = st.sidebar.selectbox("MA Type", ["sma", "ema"])
interval = st.sidebar.selectbox("Timeframe", ["15m", "30m", "1h"], index=2)

if interval == "15m":
    st.sidebar.info("Yahoo Finance only allows ~7 days of 15m data from today.")
elif interval == "30m":
    st.sidebar.info("Yahoo Finance only allows ~60 days of 30m data from today.")
elif interval == "1h":
    st.sidebar.info("Yahoo Finance only allows ~2 years of 1h data from today.")

inverse_strategy = st.sidebar.checkbox("Inverse Strategy (Flip Signals)", value=False)
stop_loss = st.sidebar.number_input("Stop Loss (points)", min_value=1, value=50)
take_profit = st.sidebar.number_input("Take Profit (points)", min_value=1, value=100)

def run_backtest(start, end, ma_20, ma_50, ma_type, interval):
    valid_intervals = ['15m', '30m', '1h']
    if interval not in valid_intervals:
        return {"error": f"Invalid interval. Must be one of: {valid_intervals}"}

    max_ma_period = max(ma_20, ma_50)
    start_dt = pd.to_datetime(start)

    if interval == '15m':
        lookback_hours = max_ma_period * 0.25
    elif interval == '30m':
        lookback_hours = max_ma_period * 0.5
    else:
        lookback_hours = max_ma_period

    data_start = start_dt - pd.Timedelta(hours=lookback_hours)

    df = yf.download("NQ=F", start=data_start, end=end, interval=interval)
    if df.empty:
        return {"error": "No data found for given period."}

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert('America/New_York')
    else:
        df.index = df.index.tz_convert('America/New_York')

    if start_dt.tzinfo is None:
        start_dt = start_dt.tz_localize('America/New_York')
    else:
        start_dt = start_dt.tz_convert('America/New_York')

    if len(df) < max(ma_20, ma_50):
        return {"error": f"Not enough data for the selected MA windows. Only {len(df)} data points available."}

    if ma_type.lower() == 'ema':
        df['ma_20'] = df['Close'].ewm(span=ma_20, adjust=False).mean()
        df['ma_50'] = df['Close'].ewm(span=ma_50, adjust=False).mean()
    else:
        df['ma_20'] = df['Close'].rolling(window=ma_20).mean()
        df['ma_50'] = df['Close'].rolling(window=ma_50).mean()

    df = df.dropna(subset=['ma_20', 'ma_50', 'Close', 'Open'])
    if df.empty:
        return {"error": "Not enough valid data after calculating moving averages."}

    df = df[df.index >= start_dt]

    df['signal'] = 0
    df.loc[df['ma_20'] > df['ma_50'], 'signal'] = 1
    df.loc[df['ma_20'] < df['ma_50'], 'signal'] = -1
    df['position_change'] = df['signal'].diff().fillna(0)

    crossovers = []
    for i in range(1, len(df) - 1):
        prev_signal = df.iloc[i-1]['signal']
        curr_signal = df.iloc[i]['signal']
        if prev_signal != curr_signal:
            if curr_signal == 1 or curr_signal == -1:
                crossovers.append({
                    "entry_time": str(df.index[i+1]),
                    "type": "long" if curr_signal == 1 else "short",
                    "ma_20": df.iloc[i]['ma_20'],
                    "ma_50": df.iloc[i]['ma_50'],
                    "entry_open": df.iloc[i+1]['Open'],
                    "prev_close": df.iloc[i]['Close']
                })

    df['datetime'] = df.index.astype(str)
    return {
        "datetime": df['datetime'].tolist(),
        "open": df['Open'].tolist(),
        "close": df['Close'].tolist(),
        "ma_20": df['ma_20'].tolist(),
        "ma_50": df['ma_50'].tolist(),
        "signal": df['signal'].tolist(),
        "crossovers": crossovers,
        "ma_type": ma_type.lower(),
        "interval": interval
    }

if st.sidebar.button("Run Backtest"):
    data = run_backtest(start_date, end_date, ma_20, ma_50, ma_type, interval)

    if "error" in data:
        st.error(data["error"])
    else:
        df = pd.DataFrame({
            "datetime": data["datetime"],
            "open": data["open"],
            "close": data["close"],
            "ma_20": data["ma_20"],
            "ma_50": data["ma_50"],
            "signal": data["signal"]
        })
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        df.set_index("datetime", inplace=True)
        crossovers = data.get("crossovers", [])
        trades = []
        account = 10000
        contract_multiplier = 20
        pnl_curve = []
        for cross in crossovers:
            entry_time = pd.to_datetime(cross["entry_time"], utc=True)
            if entry_time not in df.index:
                continue
            entry_open = df.loc[entry_time, "open"]
            position = -1 if (cross["type"] == "long" and inverse_strategy) or (cross["type"] == "short" and not inverse_strategy) else 1
            entry_price = entry_open
            exit_idx, exit_price, exit_reason = None, None, None
            for i in df.index[df.index.get_loc(entry_time)+1:]:
                price_move = (df.loc[i, "close"] - entry_price) if position == 1 else (entry_price - df.loc[i, "close"])
                if price_move >= take_profit:
                    exit_idx = i
                    exit_reason = "TP"
                    exit_price = entry_price + take_profit if position == 1 else entry_price - take_profit
                    break
                elif price_move <= -stop_loss:
                    exit_idx = i
                    exit_reason = "SL"
                    exit_price = entry_price - stop_loss if position == 1 else entry_price + stop_loss
                    break
            if exit_idx is None or exit_price is None:
                continue
            pnl = (exit_price - entry_price) * contract_multiplier if position == 1 else (entry_price - exit_price) * contract_multiplier
            account += pnl
            trades.append({
                "entry_time": entry_time,
                "exit_time": exit_idx,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "type": "long" if position == 1 else "short",
                "result": exit_reason,
                "pnl": pnl
            })
            pnl_curve.append(account)

        st.subheader("Trades")
        trades_df = pd.DataFrame(trades)
        if not trades_df.empty:
            trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True).dt.tz_convert('America/New_York')
            trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"], utc=True).dt.tz_convert('America/New_York')
            st.dataframe(trades_df)
        else:
            st.write("No trades executed.")

        st.subheader("PnL Curve ($10,000 initial, 1 NQ contract)")
        st.line_chart(pnl_curve)
