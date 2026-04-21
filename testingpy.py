from data.mt5_connector import connector
connector.connect(52848162, "your_password", "ICMarketsSC-MT5-2")
from data.mt5_connector import Timeframe
df = connector.get_rates("EURUSD", Timeframe.M15, 10)
print(df.columns.tolist())
print(df.head(2))