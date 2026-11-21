from universe_scanner import UniverseScanner

scanner = UniverseScanner(min_volume_usd=10_000_000, testnet=True)
print("Scanning top candidates across Binance universe...")
res = scanner.scan_top_candidates(max_candidates=25)

print(f"\n--- Scan Summary ---")
print(f"Total Eligible Pairs: {res['overview']['total_eligible']}")
print(f"Pairs Deep Scanned: {res['scanned_count']}")
print(f"Active Breakout Signals: {len(res['breakout_signals'])}")
for b in res['breakout_signals']:
    dir_str = "BULLISH 🚀" if b["is_bullish"] else "BEARISH 💥"
    print(f"  {b['symbol']:<10} | {dir_str} | Price: {b['price']} | VolSurge: {b['vol_surge']}x | Body: {b['disp_pct']}% | HTF: {b['htf_bias']}")

print(f"\nTop 5 Tight Squeezes (Watchlist for Breakout):")
for s in res['squeezes'][:5]:
    print(f"  {s['symbol']:<10} | Squeeze: {s['box_pct']}% | 1H: {s['htf_bias']} | VolSurge: {s['vol_surge']}x")
