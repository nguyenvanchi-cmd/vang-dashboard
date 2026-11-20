#!/usr/bin/env python3
"""Dữ liệu vĩ mô cho trang Terminal DEMO: lịch tin kinh tế tuần này/tuần sau và chỉ số đô la (DXY).

- Lịch tin: tệp JSON công khai của lịch kinh tế Forex Factory (nfs.faireconomy.media), giữ tin USD
  mức Cao/Trung bình và tin mức Cao của EUR, GBP, JPY, CNY. Giờ đổi sang giờ Việt Nam.
- DXY: Yahoo Finance mã DX-Y.NYB, nến 1 giờ 5 ngày và nến ngày 6 tháng.

Kết quả ghi vào site/data/macro.json. Nguồn nào lỗi thì giữ phần cũ của tệp, không làm hỏng cả quy trình.
"""
import datetime as dt
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "data", "macro.json")
VN = dt.timezone(dt.timedelta(hours=7))
UA = "Mozilla/5.0 (vang-dashboard macro; +https://github.com/nguyenvanchi-cmd/vang-dashboard)"

# Tên tin hay gặp → tiếng Việt (khớp theo đoạn đầu tên gốc)
VI = [
    ("Non-Farm Employment Change", "Bảng lương phi nông nghiệp (NFP)"),
    ("Unemployment Rate", "Tỷ lệ thất nghiệp"),
    ("Unemployment Claims", "Đơn trợ cấp thất nghiệp"),
    ("Core CPI", "CPI lõi"),
    ("CPI", "Lạm phát CPI"),
    ("Core PPI", "PPI lõi"),
    ("PPI", "Giá sản xuất PPI"),
    ("Core PCE Price Index", "Lạm phát PCE lõi"),
    ("Core Retail Sales", "Bán lẻ lõi"),
    ("Retail Sales", "Doanh số bán lẻ"),
    ("Federal Funds Rate", "Quyết định lãi suất Fed"),
    ("FOMC Meeting Minutes", "Biên bản họp Fed"),
    ("FOMC Statement", "Tuyên bố của Fed"),
    ("FOMC Press Conference", "Họp báo của Fed"),
    ("Fed Chair", "Chủ tịch Fed phát biểu"),
    ("Advance GDP", "GDP sơ bộ"),
    ("Prelim GDP", "GDP điều chỉnh"),
    ("Final GDP", "GDP cuối cùng"),
    ("ISM Manufacturing PMI", "PMI sản xuất ISM"),
    ("ISM Services PMI", "PMI dịch vụ ISM"),
    ("Flash Manufacturing PMI", "PMI sản xuất sơ bộ"),
    ("Flash Services PMI", "PMI dịch vụ sơ bộ"),
    ("JOLTS Job Openings", "Việc làm trống JOLTS"),
    ("ADP Non-Farm", "Việc làm ADP"),
    ("CB Consumer Confidence", "Niềm tin tiêu dùng CB"),
    ("UoM Consumer Sentiment", "Tâm lý tiêu dùng UoM"),
    ("UoM Inflation Expectations", "Kỳ vọng lạm phát UoM"),
    ("Durable Goods Orders", "Đơn hàng lâu bền"),
    ("Main Refinancing Rate", "Lãi suất ECB"),
    ("ECB President", "Chủ tịch ECB phát biểu"),
    ("Official Bank Rate", "Lãi suất BoE"),
    ("BOJ Policy Rate", "Lãi suất BoJ"),
    ("Pending Home Sales", "Doanh số nhà chờ bán"),
    ("Empire State Manufacturing", "Sản xuất Empire State"),
    ("Philly Fed Manufacturing", "Sản xuất Philly Fed"),
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def vi_title(t):
    for k, v in VI:
        if t.startswith(k) or k in t:
            return v
    return ""


def calendar():
    rows, ok = [], False
    for wk in ("thisweek", "nextweek"):
        try:
            data = get_json(f"https://nfs.faireconomy.media/ff_calendar_{wk}.json")
            ok = True
        except Exception as e:  # tuần sau thường chỉ có từ cuối tuần
            print(f"lịch {wk}: {e}")
            continue
        for x in data:
            imp, cur = x.get("impact"), x.get("country")
            if not ((cur == "USD" and imp in ("High", "Medium")) or (cur in ("EUR", "GBP", "JPY", "CNY") and imp == "High")):
                continue
            try:
                t = dt.datetime.fromisoformat(x["date"]).astimezone(dt.timezone.utc)
            except Exception:
                continue
            rows.append({
                "t": int(t.timestamp()), "cur": cur, "imp": "high" if imp == "High" else "med",
                "title": x.get("title", ""), "vi": vi_title(x.get("title", "")),
                "forecast": x.get("forecast", ""), "previous": x.get("previous", ""),
            })
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["t"], r["cur"], r["title"])):
        k = (r["t"], r["cur"], r["title"])
        if k not in seen:
            seen.add(k); out.append(r)
    return out if ok else None


def yahoo(interval, rng):
    d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval={interval}&range={rng}")
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    pts = [[t, round(c, 3)] for t, c in zip(r["timestamp"], q["close"]) if c is not None]
    return r["meta"], pts


def dxy():
    try:
        meta, hourly = yahoo("1h", "5d")
        _, daily = yahoo("1d", "6mo")
    except Exception as e:
        print(f"DXY: {e}")
        return None
    last = meta.get("regularMarketPrice") or hourly[-1][1]
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    # Ngày giao dịch trước đó lấy từ chuỗi ngày (ổn định hơn chartPreviousClose của khung 5 ngày)
    if len(daily) >= 2:
        prev = daily[-2][1]
    return {"last": round(last, 3), "prev": round(prev, 3) if prev else None, "t": meta.get("regularMarketTime"),
            "hourly": hourly[-120:], "daily": [[dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d"), c] for t, c in daily]}


def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {}
    cal, dx = calendar(), dxy()
    now = dt.datetime.now(VN)
    out = {
        "updated": now.isoformat(timespec="minutes"),
        "calendar": cal if cal is not None else old.get("calendar", []),
        "calendar_updated": now.isoformat(timespec="minutes") if cal is not None else old.get("calendar_updated"),
        "dxy": dx if dx is not None else old.get("dxy"),
        "dxy_updated": now.isoformat(timespec="minutes") if dx is not None else old.get("dxy_updated"),
        "source": "Lịch tin: Forex Factory (faireconomy.media). DXY: Yahoo Finance DX-Y.NYB.",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"macro.json: {len(out['calendar'])} tin, DXY {out['dxy'] and out['dxy']['last']}")


if __name__ == "__main__":
    main()
