# 📈 Economic News Events Scraper

> A powerful Python tool for scraping and analyzing economic news events from MyFXBook with timezone-aware filtering and impact-based windows.

## ✨ Features

- 🌍 **Multi-format Support**: CSV, XML, and HTML fallback scraping
- ⏰ **Timezone Aware**: Europe/London timezone handling
- 🎯 **Smart Filtering**: Filter by currency, impact level, and future timeframes
- 📊 **Impact-based Windows**: Configurable time windows for different impact levels
- 🚀 **Real-time Analysis**: Check active news events and predict next events
- 💾 **Export Ready**: Save filtered results to CSV

## 🚀 Quick Start

### Prerequisites

```bash
pip install requests beautifulsoup4 pandas
```

### Basic Usage

```python
from economic_news_scraper import EconomicNewsScraper, to_frame, filter_events

# Initialize scraper
scraper = EconomicNewsScraper()

# Get events for the next 7 days
events = scraper.get_myfxbook("2024-01-01", "2024-01-07")
df = to_frame(events)

# Filter high-impact USD events only
filtered = filter_events(df, 
                        start="2024-01-01", 
                        end="2024-01-07",
                        currencies=["USD"], 
                        high_only=True)
```

### Command Line Usage

```bash
# Basic scraping (next 7 days)
python economic_news_scraper.py

# Custom date range and currencies
python economic_news_scraper.py --start 2024-01-01 --end 2024-01-07 --currencies USD,EUR,GBP

# High-impact events only
python economic_news_scraper.py --high-only --save

# With export URL for better reliability
python economic_news_scraper.py --mfb-export-url "https://your-export-url.csv"
```

## 📊 Data Structure

Each news event contains:

| Field | Type | Description |
|-------|------|-------------|
| `source` | str | Data source (MyFXBook) |
| `dt` | pd.Timestamp | Event datetime (timezone-aware) |
| `currency` | str | Currency code (USD, EUR, etc.) |
| `impact` | str | Impact level (Low, Medium, High) |
| `title` | str | Event description |

## ⚙️ Configuration

### Impact-based Time Windows

```python
mins_before = {"High": 20, "Medium": 15, "Low": 10}
mins_after  = {"High": 30, "Medium": 20, "Low": 15}
```

### Supported Data Sources

- 📄 **CSV Export**: Direct CSV URL from MyFXBook
- 🗂️ **XML Export**: XML format support
- 🌐 **HTML Fallback**: Best-effort HTML scraping (less reliable)

## 🔧 Advanced Features

### Real-time Event Monitoring

```python
# Check if any news is currently active
is_active, current_event = is_news_active(df_with_windows)
if is_active:
    print(f"🔴 Active: {current_event['event']}")

# Get next upcoming event
next_event = next_news(df_with_windows)
if next_event is not None:
    print(f"⏰ Next: {next_event['event']} at {next_event['dt']}")
```

### Future Event Filtering

```python
# Get events happening in the next 60 minutes
upcoming = filter_events_by_future_minutes(df, minutes=60)
```

## 📋 Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--start` | Start date (YYYY-MM-DD) | Today |
| `--end` | End date (YYYY-MM-DD) | +7 days |
| `--currencies` | Comma-separated currency codes | USD,EUR,GBP,JPY,AUD,CAD,CHF,NZD |
| `--high-only` | Filter only high-impact events | False |
| `--mfb-export-url` | MyFXBook export URL | None |
| `--save` | Save results to CSV | False |

## 🌟 Example Output

```
===============================================
ECONOMIC EVENTS (15) — Europe/London
===============================================

📅 2024-01-15

  USD | 🔴 High   | MyFXBook     | Housing Starts (Aug)
  EUR | 🟡 Medium | MyFXBook     | ECB Interest Rate Decision
  GBP | 🟢 Low    | MyFXBook     | Retail Sales MoM

📅 2024-01-16

  USD | 🔴 High   | MyFXBook     | FOMC Meeting Minutes
  JPY | 🟡 Medium | MyFXBook     | BOJ Policy Rate
```

## 🛡️ Error Handling

- ✅ Graceful HTTP request failures
- ✅ Timezone conversion safety
- ✅ Malformed data parsing
- ✅ Rate limiting protection with rotating User-Agents

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## ⚠️ Important Notes

- **Rate Limiting**: The scraper includes user-agent rotation and request delays
- **Reliability**: HTML scraping is brittle; use CSV/XML export URLs when possible
- **Timezone**: All times are normalized to Europe/London timezone
- **Anti-bot**: Some sites may implement anti-bot measures

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Related Projects

- [Financial Data APIs](https://github.com/topics/financial-data)
- [Economic Calendar Tools](https://github.com/topics/economic-calendar)
- [Trading Automation](https://github.com/topics/trading-bot)

---

⭐ **Star this repo** if you find it useful!

🐛 **Found a bug?** [Open an issue](https://github.com/yourusername/economic-news-scraper/issues)

📧 **Questions?** Feel free to reach out!
