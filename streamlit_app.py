import streamlit as st
import requests
import pandas as pd
import datetime

st.title("NQ MA Crossover Backtester")

# Sidebar for user input
st.sidebar.header("Strategy Settings")
start_date = st.sidebar.date_input("Start Date", datetime.date(2024, 4, 1))
end_date = st.sidebar.date_input("End Date", datetime.date(2024, 5, 1))
ma_20 = st.sidebar.number_input("MA 1 Period (default 20)", min_value=1, value=20)
ma_50 = st.sidebar.number_input("MA 2 Period (default 50)", min_value=1, value=50)
ma_type = st.sidebar.selectbox("MA Type", ["sma", "ema"])
interval = st.sidebar.selectbox("Timeframe", ["15m", "30m", "1h"], index=2)

# Add dynamic disclaimer for max lookback
if interval == "15m":
    st.sidebar.info("Yahoo Finance only allows ~7 days of 15m data from today.")
elif interval == "30m":
    st.sidebar.info("Yahoo Finance only allows ~60 days of 30m data from today.")
elif interval == "1h":
    st.sidebar.info("Yahoo Finance only allows ~2 years of 1h data from today.")

inverse_strategy = st.sidebar.checkbox("Inverse Strategy (Flip Signals)", value=False, 
                                     help="When checked: Long when MA signal is short, Short when MA signal is long")
stop_loss = st.sidebar.number_input("Stop Loss (points)", min_value=1, value=50)
take_profit = st.sidebar.number_input("Take Profit (points)", min_value=1, value=100)

# Show inverse strategy status
if inverse_strategy:
    st.warning("🔄 **Inverse Strategy Active**: Long when MA signal is short, Short when MA signal is long")
else:
    st.info("📈 **Normal Strategy**: Long when MA signal is long, Short when MA signal is short")

if st.sidebar.button("Run Backtest"):
    # Fetch data from FastAPI backend
    params = {
        "start": start_date.strftime("%Y-%m-%d"),
        "end": end_date.strftime("%Y-%m-%d"),
        "ma_20": ma_20,
        "ma_50": ma_50,
        "ma_type": ma_type,
        "interval": interval
    }
    
    url = "http://localhost:8000/backtest/ma-crossover"
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        st.error(f"API error: {resp.text}")
    else:
        data = resp.json()
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
            position = 0
            entry_price = 0
            contract_multiplier = 20  # $ per point
            pnl_curve = []
            trade_open_idx = None
            # Build a lookup for open prices
            open_lookup = df["open"].to_dict()
            for cross in crossovers:
                entry_time = pd.to_datetime(cross["entry_time"], utc=True)
                if entry_time not in df.index:
                    continue
                entry_open = df.loc[entry_time, "open"]
                
                # Determine position based on inverse strategy setting
                if inverse_strategy:
                    position = -1 if cross["type"] == "long" else 1
                else:
                    position = 1 if cross["type"] == "long" else -1
                
                entry_price = entry_open
                trade_open_idx = entry_time
                # Find exit: TP or SL only
                exit_idx = None
                exit_reason = None
                exit_price = None
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
                # If neither SL nor TP is hit, skip this trade (do not record it)
                if exit_idx is None or exit_price is None:
                    continue
                pnl = (exit_price - entry_price) * contract_multiplier if position == 1 else (entry_price - exit_price) * contract_multiplier
                account += pnl
                trades.append({
                    "entry_time": trade_open_idx,
                    "exit_time": exit_idx,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "type": "long" if position == 1 else "short",
                    "result": exit_reason,
                    "pnl": pnl
                })
                pnl_curve.append(account)
            # Show trades
            st.subheader("Trades")
            trades_df = pd.DataFrame(trades)
            if not trades_df.empty:
                trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], utc=True).dt.tz_convert('America/New_York')
                trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"], utc=True).dt.tz_convert('America/New_York')
                st.dataframe(trades_df)
            else:
                st.write("No trades executed.")
            # Show PnL chart
            st.subheader("PnL Curve ($10,000 initial, 1 NQ contract)")
            st.line_chart(pnl_curve) 