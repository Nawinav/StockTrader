"""Static universe of NSE-listed stocks with fundamental metadata.

In production this would come from a DB or a daily fundamentals feed
(screener.in / tickertape / Upstox instruments dump). For the MVP we keep
a curated list of ~40 liquid Nifty constituents with sensible placeholder
fundamentals so the scoring engine has something to work with.
"""
from dataclasses import dataclass, asdict
from typing import Dict, List


@dataclass
class StockMeta:
    symbol: str          # NSE trading symbol
    name: str
    sector: str
    # Fundamental snapshot (annual). Values are illustrative; the
    # scoring engine normalises them so exact accuracy is not critical
    # for the MVP.
    market_cap_cr: float      # in INR crore
    pe: float                 # trailing P/E
    pb: float                 # price / book
    roe: float                # return on equity %
    debt_to_equity: float     # D/E ratio
    eps_growth_3y: float      # 3-yr EPS CAGR %
    revenue_growth_3y: float  # 3-yr revenue CAGR %
    dividend_yield: float     # %
    promoter_holding: float   # %

    def as_dict(self) -> Dict:
        return asdict(self)


UNIVERSE: List[StockMeta] = [
    StockMeta("RELIANCE", "Reliance Industries", "Energy",        1800000, 24.1, 2.2, 9.1,  0.42, 11.3, 14.2, 0.35, 50.3),
    StockMeta("TCS",      "Tata Consultancy Services", "IT",      1350000, 30.2, 14.5, 46.2, 0.05, 10.4, 12.8, 1.35, 72.3),
    StockMeta("HDFCBANK", "HDFC Bank", "Banking",                 1200000, 18.6, 2.9, 17.1, 0.00,  9.7, 15.1, 1.15, 25.7),
    StockMeta("INFY",     "Infosys", "IT",                         680000, 25.4, 7.2, 31.8, 0.09,  8.1, 11.4, 2.10, 14.9),
    StockMeta("ICICIBANK","ICICI Bank", "Banking",                 780000, 17.9, 2.6, 18.4, 0.00, 22.1, 17.3, 0.80,  0.0),
    StockMeta("HINDUNILVR","Hindustan Unilever", "FMCG",           550000, 56.3, 11.0, 19.5, 0.03, 11.2,  8.4, 1.80, 61.9),
    StockMeta("ITC",      "ITC", "FMCG",                           520000, 26.5, 7.4, 28.1, 0.00,  9.4,  7.1, 3.45, 0.0),
    StockMeta("LT",       "Larsen & Toubro", "Infrastructure",     480000, 35.2, 4.6, 13.2, 0.41, 12.6, 14.9, 0.85, 0.0),
    StockMeta("SBIN",     "State Bank of India", "Banking",        650000, 10.4, 1.7, 16.8, 0.00, 18.4, 12.2, 1.30, 57.6),
    StockMeta("BHARTIARTL","Bharti Airtel", "Telecom",             720000, 72.1, 8.4, 13.5, 1.32, 18.2, 15.4, 0.45, 53.2),
    StockMeta("KOTAKBANK","Kotak Mahindra Bank", "Banking",        360000, 19.2, 3.0, 14.6, 0.00, 14.0, 13.4, 0.12, 25.9),
    StockMeta("AXISBANK", "Axis Bank", "Banking",                  340000, 15.1, 2.3, 15.9, 0.00, 19.8, 14.0, 0.10,  8.2),
    StockMeta("ASIANPAINT","Asian Paints", "FMCG",                 275000, 48.9, 12.8, 27.3, 0.12,  7.2,  9.8, 0.95, 52.6),
    StockMeta("MARUTI",   "Maruti Suzuki", "Auto",                 370000, 28.7, 4.6, 16.4, 0.01, 24.1, 15.2, 1.05, 58.3),
    StockMeta("BAJFINANCE","Bajaj Finance", "NBFC",                425000, 32.4, 5.4, 23.5, 3.80, 22.1, 28.4, 0.16, 55.9),
    StockMeta("SUNPHARMA","Sun Pharmaceutical", "Pharma",          370000, 34.5, 5.1, 15.7, 0.08,  9.5,  8.2, 0.70, 54.5),
    StockMeta("TITAN",    "Titan Company", "Consumer Discretionary", 310000, 88.4, 26.3, 32.8, 0.67, 17.8, 22.0, 0.30, 52.9),
    StockMeta("ULTRACEMCO","UltraTech Cement", "Cement",           280000, 39.7, 4.3, 11.2, 0.16,  8.9, 10.3, 0.40, 59.9),
    StockMeta("NESTLEIND","Nestle India", "FMCG",                  235000, 78.2, 68.1, 102.3, 0.00, 12.8, 11.2, 1.10, 62.8),
    StockMeta("WIPRO",    "Wipro", "IT",                           230000, 22.1, 3.2, 14.3, 0.22,  5.2,  6.1, 0.80, 72.9),
    StockMeta("POWERGRID","Power Grid Corporation", "Power",       260000, 18.4, 2.7, 19.1, 1.34,  6.8,  4.2, 4.10, 51.3),
    StockMeta("NTPC",     "NTPC", "Power",                         330000, 15.6, 2.1, 13.5, 1.46,  8.5,  9.0, 2.50, 51.1),
    StockMeta("ONGC",     "Oil & Natural Gas Corp", "Energy",      320000,  9.2, 1.1, 17.8, 0.45,  5.1,  6.4, 4.60, 58.9),
    StockMeta("COALINDIA","Coal India", "Mining",                  280000,  9.6, 3.6, 58.4, 0.06, 15.4, 12.7, 6.80, 66.1),
    StockMeta("TATAMOTORS","Tata Motors", "Auto",                  300000, 14.3, 4.9, 21.1, 1.15, 32.4, 17.2, 0.20, 46.4),
    StockMeta("TATASTEEL","Tata Steel", "Metals",                  180000, 17.4, 2.2, 10.4, 0.74,  7.8,  8.2, 2.70, 33.9),
    StockMeta("JSWSTEEL", "JSW Steel", "Metals",                   200000, 22.5, 3.1,  9.7, 1.18, 14.2, 13.1, 0.80, 45.0),
    StockMeta("HCLTECH",  "HCL Technologies", "IT",                420000, 24.9, 5.7, 22.8, 0.07,  9.6, 10.4, 3.40, 60.8),
    StockMeta("TECHM",    "Tech Mahindra", "IT",                   140000, 28.1, 4.2, 14.1, 0.09,  4.6,  7.2, 2.00, 35.1),
    StockMeta("ADANIENT", "Adani Enterprises", "Conglomerate",     320000, 82.4, 6.7,  9.2, 1.78, 28.4, 31.2, 0.06, 72.6),
    StockMeta("ADANIPORTS","Adani Ports & SEZ", "Infrastructure",  260000, 31.4, 4.1, 15.2, 0.91, 14.1, 18.4, 0.45, 65.9),
    StockMeta("DIVISLAB", "Divi's Laboratories", "Pharma",         130000, 46.7, 6.8, 14.3, 0.01,  4.2,  5.1, 0.70, 51.9),
    StockMeta("DRREDDY",  "Dr. Reddy's Laboratories", "Pharma",    105000, 21.3, 3.6, 18.7, 0.06, 12.3,  9.8, 0.75, 26.7),
    StockMeta("CIPLA",    "Cipla", "Pharma",                       125000, 27.2, 4.1, 15.8, 0.04, 11.7, 10.3, 0.65, 33.4),
    StockMeta("BAJAJFINSV","Bajaj Finserv", "NBFC",                265000, 35.1, 4.2, 14.9, 3.42, 15.3, 21.2, 0.06, 60.7),
    StockMeta("HEROMOTOCO","Hero MotoCorp", "Auto",                 95000, 21.6, 5.6, 23.1, 0.00,  4.8,  6.2, 3.40, 34.8),
    StockMeta("EICHERMOT","Eicher Motors", "Auto",                  110000, 30.5, 6.4, 23.7, 0.01, 14.4, 16.1, 0.80, 49.2),
    StockMeta("BPCL",     "Bharat Petroleum", "Energy",             130000,  6.2, 1.4, 27.3, 0.94, 12.4,  7.8, 5.80, 52.9),
    StockMeta("GRASIM",   "Grasim Industries", "Conglomerate",      160000, 28.1, 1.6,  8.4, 0.49, 12.1, 11.5, 0.45, 43.0),
    StockMeta("BRITANNIA","Britannia Industries", "FMCG",           110000, 56.1, 30.7, 56.3, 0.64,  9.8, 12.0, 1.50, 50.6),
]


def get_universe() -> List[StockMeta]:
    return list(UNIVERSE)


def get_by_symbol(symbol: str) -> StockMeta | None:
    symbol = symbol.upper()
    for s in UNIVERSE:
        if s.symbol == symbol:
            return s
    return None
