#!/usr/bin/env python3
"""Lấy dữ liệu cho website Vàng hôm nay.

- Giá XAU/USD theo ngày. Nguồn chính: Dukascopy (giá giao ngay, giá chào mua, nến ngày theo giờ UTC),
  lấy từ các tệp dữ liệu công khai datafeed.dukascopy.com. Dự phòng: Yahoo GC=F (hiệu chỉnh về mặt bằng
  giá giao ngay), Stooq.
- Tỷ giá USD/VND (Vietcombank; dự phòng: open.er-api.com).
- Giá vàng trong nước (SJC, PNJ) nếu lấy được.

Mỗi nguồn lỗi chỉ được ghi lại, không làm dừng cả quy trình: dữ liệu cũ trong thư mục data/ vẫn được giữ.
"""
import io
import json
import lzma
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import datetime as dt

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
VN = dt.timezone(dt.timedelta(hours=7))
NOW = dt.datetime.now(VN)
NOW_UTC = NOW.astimezone(dt.timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
UA = "vang-dashboard/1.0 (+https://github.com/nguyenvanchi-cmd/vang-dashboard)"

PRICE_FILE = os.path.join(DATA_DIR, "xauusd_daily.csv")
FX_FILE = os.path.join(DATA_DIR, "usd_vnd.csv")
DOM_FILE = os.path.join(DATA_DIR, "domestic.csv")
STATUS_FILE = os.path.join(DATA_DIR, "fetch_status.json")
CLAUDE_FILE = os.path.join(DATA_DIR, "claude_daily.json")

status = {"run_at": NOW.isoformat(timespec="seconds"), "steps": []}


def note(step, ok, msg=""):
    status["steps"].append({"step": step, "ok": bool(ok), "msg": str(msg)[:300]})
    print(("OK   " if ok else "FAIL ") + step + ": " + str(msg)[:300], flush=True)


class HTTPStatus(Exception):
    def __init__(self, code, url):
        super().__init__(f"HTTP {code}")
        self.code = code
        self.url = url


def get(url, data=None, headers=None, timeout=40):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "vi,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise HTTPStatus(exc.code, url) from exc


# ---------------------------------------------------------------- giá thế giới: Dukascopy
DUKA = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
DUKA_SCALE = 1000.0          # XAU/USD: giá lưu dạng số nguyên, chia 1000
DUKA_START_YEAR = 2003
duka_stats = {"req": 0, "miss": 0}


def duka_raw(path):
    """Tải và giải nén một tệp .bi5; tệp không tồn tại hoặc rỗng trả về b''."""
    url = f"{DUKA}/{path}"
    last = None
    for attempt in range(3):
        try:
            duka_stats["req"] += 1
            raw = get(url, timeout=30)
            time.sleep(0.15)
            return lzma.decompress(raw) if raw else b""
        except HTTPStatus as exc:
            if exc.code == 404:
                duka_stats["miss"] += 1
                return b""
            last = exc
        except lzma.LZMAError:
            return b""
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Dukascopy {path}: {last}")


def _order(px):
    """Xác định vị trí cột cao nhất/thấp nhất; hai cột còn lại theo thứ tự là mở cửa, đóng cửa."""
    if len(px) == 0:
        return 0, 1, 2, 3
    mx = px.max(axis=1, keepdims=True)
    mn = px.min(axis=1, keepdims=True)
    hi = int(np.argmax((px == mx).sum(axis=0)))
    lo = int(np.argmax((px == mn).sum(axis=0)))
    if hi == lo:
        return 0, 1, 2, 3
    rest = [i for i in range(4) if i not in (hi, lo)]
    return rest[0], hi, lo, rest[1]


def duka_candles(buf, base):
    """Nến Dukascopy: mỗi bản ghi 24 byte (thời điểm, 4 giá, khối lượng), big-endian."""
    n = len(buf) // 24
    if n == 0:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    arr = np.frombuffer(buf[: n * 24], dtype=np.dtype([("t", ">i4"), ("p", ">i4", (4,)), ("v", ">f4")]))
    t = arr["t"].astype("int64")
    if t.max() > 400 * 86400:   # mili giây
        t = t // 1000
    px = arr["p"].astype("float64") / DUKA_SCALE
    o, h, l, c = _order(px)
    df = pd.DataFrame({"ts": pd.Timestamp(base) + pd.to_timedelta(t, unit="s"),
                       "open": px[:, o], "high": px[:, h], "low": px[:, l], "close": px[:, c],
                       "volume": arr["v"].astype("float64")})
    # Bỏ nến lấp chỗ trống (giá đứng yên, không có khối lượng) của ngày nghỉ.
    return df[(df["volume"] > 0) | (df["high"] > df["low"])]


def duka_ticks(buf, base):
    """Tick Dukascopy: mỗi bản ghi 20 byte (mili giây, giá bán, giá mua, khối lượng bán, khối lượng mua)."""
    n = len(buf) // 20
    if n == 0:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    arr = np.frombuffer(buf[: n * 20], dtype=np.dtype([("t", ">i4"), ("ask", ">i4"), ("bid", ">i4"),
                                                       ("av", ">f4"), ("bv", ">f4")]))
    bid = arr["bid"].astype("float64") / DUKA_SCALE
    ts = pd.Timestamp(base) + pd.to_timedelta(arr["t"].astype("int64"), unit="ms")
    return pd.DataFrame({"ts": ts, "open": bid, "high": bid, "low": bid, "close": bid,
                         "volume": arr["bv"].astype("float64")})


def to_daily(df):
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    df = df.sort_values("ts")
    g = df.groupby(df["ts"].dt.strftime("%Y-%m-%d"))
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last()})
    out.index.name = "date"
    return out.reset_index()


def duka_day(day):
    """Một ngày UTC: tệp nến phút; nếu chưa có (ngày gần nhất) thì gộp tick từng giờ đã kết thúc."""
    base = dt.datetime(day.year, day.month, day.day)
    buf = duka_raw(f"{day.year}/{day.month - 1:02d}/{day.day:02d}/BID_candles_min_1.bi5")
    if buf:
        return to_daily(duka_candles(buf, base))
    if (NOW_UTC.date() - day).days > 3:
        return to_daily(None)
    parts = []
    for hr in range(24):
        hb = base + dt.timedelta(hours=hr)
        if hb + dt.timedelta(hours=1) > NOW_UTC.replace(tzinfo=None):
            break
        tb = duka_raw(f"{day.year}/{day.month - 1:02d}/{day.day:02d}/{hr:02d}h_ticks.bi5")
        if tb:
            parts.append(duka_ticks(tb, hb))
    return to_daily(pd.concat(parts) if parts else None)


def duka_month(y, m, since):
    base = dt.datetime(y, m, 1)
    is_current = (y, m) == (NOW_UTC.year, NOW_UTC.month)
    if not is_current:
        buf = duka_raw(f"{y}/{m - 1:02d}/BID_candles_hour_1.bi5")
        if buf:
            return to_daily(duka_candles(buf, base))
        # Tháng vừa kết thúc có thể chưa có tệp gộp: đi từng ngày.
        if (NOW_UTC.year * 12 + NOW_UTC.month) - (y * 12 + m) > 1:
            return to_daily(None)
    frames = []
    d = max(dt.date(y, m, 1), since)
    while d.month == m and d <= NOW_UTC.date():
        if d == NOW_UTC.date() and NOW_UTC.hour < 21:
            break
        if d.weekday() < 5:
            frames.append(duka_day(d))
        d += dt.timedelta(days=1)
    return pd.concat(frames) if frames else to_daily(None)


def duka_year(y, since):
    if y < NOW_UTC.year:
        buf = duka_raw(f"{y}/BID_candles_day_1.bi5")
        if buf:
            return to_daily(duka_candles(buf, dt.datetime(y, 1, 1)))
        if y < NOW_UTC.year - 1:
            return to_daily(None)
    last_m = 12 if y < NOW_UTC.year else NOW_UTC.month
    first_m = since.month if since.year == y else 1
    frames = [duka_month(y, m, since) for m in range(first_m, last_m + 1)]
    return pd.concat(frames) if frames else to_daily(None)


def from_dukascopy(since=None):
    since = since or dt.date(DUKA_START_YEAR, 1, 1)
    frames = [duka_year(y, since) for y in range(since.year, NOW_UTC.year + 1)]
    df = pd.concat(frames, ignore_index=True)
    if len(df) == 0:
        raise ValueError(f"không có dữ liệu ({duka_stats['req']} yêu cầu, {duka_stats['miss']} tệp không tồn tại)")
    df["wd"] = pd.to_datetime(df["date"]).dt.weekday
    df = df[(df["wd"] < 5) & (df["date"] >= since.strftime("%Y-%m-%d"))].drop(columns="wd")
    # Ngày UTC hiện tại chỉ lấy khi phiên New York đã gần kết thúc.
    if NOW_UTC.hour < 21:
        df = df[df["date"] < NOW_UTC.strftime("%Y-%m-%d")]
    df = df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    # Kiểm tra hệ số quy đổi giá: giá gần nhất phải khớp mặt bằng giá vàng hiện tại.
    anchor = claude_anchor()
    med = float(df["close"].tail(5).median())
    for k in (1.0, 0.1, 10.0, 0.01, 100.0):
        v = med * k
        if (anchor and 0.7 * anchor < v < 1.3 * anchor) or (not anchor and 1000 < v < 10000):
            break
    else:
        k = 1.0
    if k != 1.0:
        for c in ["open", "high", "low", "close"]:
            df[c] = df[c] * k
    df["source"] = "Dukascopy XAU/USD (giá mua, ngày UTC)"
    return df


# ---------------------------------------------------------------- giá thế giới: dự phòng
def from_yahoo(symbol="GC=F"):
    last = None
    for host in ("query2", "query1"):
        url = (f"https://{host}.finance.yahoo.com/v8/finance/chart/"
               + urllib.parse.quote(symbol) + "?range=max&interval=1d")
        for attempt in range(2):
            try:
                js = json.loads(get(url, headers={"Accept": "application/json"}))
                res = js["chart"]["result"][0]
                q = res["indicators"]["quote"][0]
                df = pd.DataFrame({"ts": res["timestamp"], "open": q["open"], "high": q["high"],
                                   "low": q["low"], "close": q["close"]}).dropna()
                df["date"] = (pd.to_datetime(df["ts"], unit="s", utc=True)
                              .dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d"))
                df = df.drop(columns="ts").drop_duplicates("date", keep="last")
                df["source"] = "Yahoo " + symbol
                return df[["date", "open", "high", "low", "close", "source"]]
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(4 * (attempt + 1))
    raise RuntimeError(last)


def from_stooq():
    raw = get("https://stooq.com/q/d/l/?s=xauusd&i=d").decode("utf-8", "replace")
    df = pd.read_csv(io.StringIO(raw))
    cols = {c.strip().lower(): c for c in df.columns}
    need = ["date", "open", "high", "low", "close"]
    if not all(k in cols for k in need):
        raise ValueError("Stooq không trả về dữ liệu CSV (trang kiểm tra truy cập tự động)")
    df = df.rename(columns={cols[k]: k for k in need})[need]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["source"] = "Stooq XAUUSD"
    return df


def claude_anchor():
    """Giá XAU/USD Claude ghi nhận trong báo cáo sáng (để kiểm tra chéo)."""
    try:
        with open(CLAUDE_FILE, encoding="utf-8") as f:
            js = json.load(f)
        v = float(js.get("xau_usd"))
        age = (pd.Timestamp(TODAY) - pd.Timestamp(str(js.get("ngay"))[:10])).days
        return v if 200 < v < 20000 and age <= 7 else None
    except Exception:  # noqa: BLE001
        return None


def check_prices(df, name):
    if df is None or len(df) < 200:
        raise ValueError(f"{name}: quá ít dòng ({0 if df is None else len(df)})")
    df = df.sort_values("date")
    last = df.iloc[-1]
    if not (200 < float(last["close"]) < 20000):
        raise ValueError(f"{name}: giá cuối bất thường {last['close']}")
    age = (pd.Timestamp(TODAY) - pd.Timestamp(last["date"])).days
    if age > 10:
        raise ValueError(f"{name}: dữ liệu cũ, ngày cuối {last['date']}")
    jump = df["close"].astype(float).pct_change().abs().max()
    if jump > 0.25:
        raise ValueError(f"{name}: có bước nhảy giá bất thường {jump:.0%}")
    anchor = claude_anchor()
    if anchor and abs(float(last["close"]) / anchor - 1) > 0.15:
        raise ValueError(f"{name}: giá cuối {last['close']} lệch xa giá Claude ghi nhận {anchor}")
    return df


def load_existing_prices():
    if os.path.exists(PRICE_FILE):
        return pd.read_csv(PRICE_FILE, dtype={"date": str})
    return None


def update_prices():
    old = load_existing_prices()
    has_old = old is not None and len(old) > 200
    duka_old = has_old and old["source"].astype(str).str.startswith("Dukascopy").mean() > 0.9

    # 1) Dukascopy: lần đầu lấy toàn bộ lịch sử; các lần sau chỉ làm mới 10 ngày gần nhất.
    try:
        if duka_old:
            since = (pd.Timestamp(old["date"].max()) - pd.Timedelta(days=10)).date()
            new = from_dukascopy(since)
            df = pd.concat([old, new]).drop_duplicates("date", keep="last")
        else:
            df = from_dukascopy()
        df = check_prices(df, "Dukascopy")
        note("Giá XAU/USD (Dukascopy)", True,
             f"{len(df)} dòng, {df['date'].min()} → {df['date'].max()}, {duka_stats['req']} yêu cầu")
        return df
    except Exception as exc:  # noqa: BLE001
        note("Giá XAU/USD (Dukascopy)", False, f"{exc} ({duka_stats['req']} yêu cầu)")

    # 2) Yahoo GC=F: hợp đồng tương lai, hiệu chỉnh về mặt bằng giá giao ngay nếu đã có lịch sử.
    try:
        yf = from_yahoo("GC=F")
        if has_old:
            both = old.merge(yf, on="date", suffixes=("_s", "_f"))
            ratio = (both["close_s"] / both["close_f"]).tail(20).median() if len(both) >= 5 else 1.0
            add = yf[~yf["date"].isin(old["date"])].copy()
            for c in ["open", "high", "low", "close"]:
                add[c] = add[c] * ratio
            add["source"] = f"Yahoo GC=F × {ratio:.4f}"
            df = pd.concat([old, add]).drop_duplicates("date", keep="last")
        else:
            df = yf
        df = check_prices(df, "Yahoo GC=F")
        note("Giá XAU/USD (Yahoo dự phòng)", True, f"{len(df)} dòng, ngày cuối {df['date'].max()}")
        return df
    except Exception as exc:  # noqa: BLE001
        note("Giá XAU/USD (Yahoo dự phòng)", False, exc)

    # 3) Stooq.
    try:
        df = from_stooq()
        if has_old:
            df = pd.concat([old, df]).drop_duplicates("date", keep="last")
        df = check_prices(df, "Stooq")
        note("Giá XAU/USD (Stooq dự phòng)", True, f"{len(df)} dòng, ngày cuối {df['date'].max()}")
        return df
    except Exception as exc:  # noqa: BLE001
        note("Giá XAU/USD (Stooq dự phòng)", False, exc)
    return old


# ---------------------------------------------------------------- tỷ giá
def usd_vnd():
    try:
        raw = get("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx")
        root = ET.fromstring(raw)
        for ex in root.iter("Exrate"):
            if ex.get("CurrencyCode") == "USD":
                num = lambda s: float(str(s).replace(",", "")) if s and s.strip() != "-" else None  # noqa: E731
                row = {"buy": num(ex.get("Buy")), "transfer": num(ex.get("Transfer")),
                       "sell": num(ex.get("Sell")), "source": "Vietcombank"}
                if row["sell"] and 15000 < row["sell"] < 40000:
                    note("Tỷ giá USD/VND (Vietcombank)", True, row["sell"])
                    return row
        raise ValueError("không thấy USD trong XML")
    except Exception as exc:  # noqa: BLE001
        note("Tỷ giá USD/VND (Vietcombank)", False, exc)
    try:
        js = json.loads(get("https://open.er-api.com/v6/latest/USD"))
        v = float(js["rates"]["VND"])
        note("Tỷ giá USD/VND (open.er-api)", True, v)
        return {"buy": None, "transfer": None, "sell": v, "source": "open.er-api.com (tỷ giá trung bình)"}
    except Exception as exc:  # noqa: BLE001
        note("Tỷ giá USD/VND (open.er-api)", False, exc)
    return None


def save_fx(row):
    if not row:
        return
    old = pd.read_csv(FX_FILE, dtype={"date": str}) if os.path.exists(FX_FILE) else pd.DataFrame()
    new = pd.DataFrame([{"date": TODAY, **row}])
    out = pd.concat([old, new]).drop_duplicates("date", keep="last").sort_values("date")
    out.to_csv(FX_FILE, index=False)


# ---------------------------------------------------------------- giá trong nước
def to_trieu(v):
    x = float(str(v).replace(",", "").strip())
    for div in (1e6, 1e3, 1.0):          # theo lượng: đồng, nghìn đồng, triệu đồng
        y = x / div
        if 50 <= y <= 600:
            return round(y, 2)
    for div in (1e5, 1e2):               # theo chỉ (1 lượng = 10 chỉ): đồng, nghìn đồng
        y = x / div
        if 50 <= y <= 600:
            return round(y, 2)
    raise ValueError(f"giá lạ {v}")


def from_sjc():
    body = urllib.parse.urlencode({"method": "GetCurrentGoldPricesByBranch", "BranchId": "1"}).encode()
    raw = get("https://sjc.com.vn/GoldPrice/Services/PriceService.ashx", data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest", "Referer": "https://sjc.com.vn/"})
    js = json.loads(raw)
    rows, seen = [], set()
    for it in js.get("data", []):
        name = str(it.get("TypeName", "")).lower()
        if "1l" in name and "sjc" in name:
            prod = "Miếng SJC"
        elif "nhẫn" in name and ("1 chỉ" in name or "99,99" in name or "9999" in name):
            prod = "Nhẫn 9999"
        else:
            continue
        if prod in seen:
            continue
        seen.add(prod)
        rows.append({"brand": "SJC", "product": prod,
                     "buy": to_trieu(it.get("BuyValue") or it.get("Buy")),
                     "sell": to_trieu(it.get("SellValue") or it.get("Sell")), "source": "sjc.com.vn"})
    if not rows:
        raise ValueError("không đọc được dòng giá nào")
    return rows


def from_pnj():
    js = json.loads(get("https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price?zone=00"))
    rows, seen = [], set()
    for it in js.get("data", []):
        code = str(it.get("masp", "")).upper()
        name = str(it.get("tensp", "")).lower()
        if code == "SJC" or "sjc" in name:
            prod = "Miếng SJC"
        elif "nhẫn" in name or code in ("N24K", "NHAN"):
            prod = "Nhẫn 9999"
        else:
            continue
        if prod in seen:
            continue
        seen.add(prod)
        rows.append({"brand": "PNJ", "product": prod, "buy": to_trieu(it.get("giamua")),
                     "sell": to_trieu(it.get("giaban")), "source": "pnj.com.vn"})
    if not rows:
        raise ValueError("không đọc được dòng giá nào")
    return rows


def update_domestic():
    rows = []
    for name, fn in (("SJC", from_sjc), ("PNJ", from_pnj)):
        try:
            got = fn()
            rows += got
            note(f"Giá trong nước ({name})", True, f"{len(got)} dòng")
        except Exception as exc:  # noqa: BLE001
            note(f"Giá trong nước ({name})", False, exc)
    if not rows:
        return
    stamp = NOW.strftime("%H:%M")
    new = pd.DataFrame([{"date": TODAY, "time": stamp, **r} for r in rows])
    old = pd.read_csv(DOM_FILE, dtype={"date": str}) if os.path.exists(DOM_FILE) else pd.DataFrame()
    out = (pd.concat([old, new]).drop_duplicates(["date", "brand", "product"], keep="last")
           .sort_values(["date", "brand", "product"]))
    out.to_csv(DOM_FILE, index=False)


def main():
    prices = update_prices()
    if prices is not None and len(prices):
        prices = prices.sort_values("date")
        for c in ["open", "high", "low", "close"]:
            prices[c] = prices[c].astype(float).round(2)
        prices.to_csv(PRICE_FILE, index=False)
    save_fx(usd_vnd())
    update_domestic()
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
