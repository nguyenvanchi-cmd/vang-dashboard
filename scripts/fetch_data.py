#!/usr/bin/env python3
"""Lấy dữ liệu cho website Vàng hôm nay.

- Giá XAU/USD theo ngày (nguồn chính: Stooq; dự phòng: Yahoo GC=F, được hiệu chỉnh về mặt bằng giá giao ngay).
- Tỷ giá USD/VND (Vietcombank; dự phòng: open.er-api.com).
- Giá vàng trong nước (SJC, PNJ) nếu lấy được.

Mỗi nguồn lỗi chỉ được ghi lại, không làm dừng cả quy trình: dữ liệu cũ trong thư mục data/ vẫn được giữ.
"""
import io
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import datetime as dt

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
VN = dt.timezone(dt.timedelta(hours=7))
NOW = dt.datetime.now(VN)
TODAY = NOW.strftime("%Y-%m-%d")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

PRICE_FILE = os.path.join(DATA_DIR, "xauusd_daily.csv")
FX_FILE = os.path.join(DATA_DIR, "usd_vnd.csv")
DOM_FILE = os.path.join(DATA_DIR, "domestic.csv")
STATUS_FILE = os.path.join(DATA_DIR, "fetch_status.json")

status = {"run_at": NOW.isoformat(timespec="seconds"), "steps": []}


def note(step, ok, msg=""):
    status["steps"].append({"step": step, "ok": bool(ok), "msg": str(msg)[:300]})
    print(("OK   " if ok else "FAIL ") + step + ": " + str(msg)[:300], flush=True)


def get(url, data=None, headers=None, timeout=40):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "vi,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------- giá thế giới
def from_stooq():
    raw = get("https://stooq.com/q/d/l/?s=xauusd&i=d").decode("utf-8", "replace")
    df = pd.read_csv(io.StringIO(raw))
    cols = {c.strip().lower(): c for c in df.columns}
    need = ["date", "open", "high", "low", "close"]
    if not all(k in cols for k in need):
        raise ValueError("Stooq trả về định dạng lạ: " + raw[:120].replace("\n", " "))
    df = df.rename(columns={cols[k]: k for k in need})[need]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["source"] = "Stooq XAUUSD"
    return df


def from_yahoo(symbol="GC=F"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(symbol) + "?range=max&interval=1d")
    js = json.loads(get(url))
    res = js["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": res["timestamp"], "open": q["open"], "high": q["high"],
                       "low": q["low"], "close": q["close"]}).dropna()
    df["date"] = (pd.to_datetime(df["ts"], unit="s", utc=True)
                  .dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d"))
    df = df.drop(columns="ts").drop_duplicates("date", keep="last")
    df["source"] = "Yahoo " + symbol
    return df[["date", "open", "high", "low", "close", "source"]]


def check_prices(df, name):
    if df is None or len(df) < 200:
        raise ValueError(f"{name}: quá ít dòng")
    last = df.sort_values("date").iloc[-1]
    if not (200 < float(last["close"]) < 20000):
        raise ValueError(f"{name}: giá cuối bất thường {last['close']}")
    age = (pd.Timestamp(TODAY) - pd.Timestamp(last["date"])).days
    if age > 10:
        raise ValueError(f"{name}: dữ liệu cũ, ngày cuối {last['date']}")
    return df


def load_existing_prices():
    if os.path.exists(PRICE_FILE):
        return pd.read_csv(PRICE_FILE, dtype={"date": str})
    return None


def update_prices():
    old = load_existing_prices()
    try:
        df = check_prices(from_stooq(), "Stooq")
        if old is not None and len(old):
            # Stooq trả về toàn bộ lịch sử: lấy bản mới, giữ thêm những ngày cũ mà bản mới không có.
            df = pd.concat([old, df]).drop_duplicates("date", keep="last")
        note("Giá XAU/USD (Stooq)", True, f"{len(df)} dòng, ngày cuối {df['date'].max()}")
        return df
    except Exception as exc:  # noqa: BLE001
        note("Giá XAU/USD (Stooq)", False, exc)

    try:
        yf = check_prices(from_yahoo("GC=F"), "Yahoo GC=F")
        if old is not None and len(old) > 200:
            # Hiệu chỉnh giá hợp đồng tương lai về mặt bằng giá giao ngay bằng tỷ lệ trung vị
            # trên 20 ngày trùng nhau gần nhất, rồi chỉ thêm những ngày còn thiếu.
            both = old.merge(yf, on="date", suffixes=("_s", "_f"))
            if len(both) >= 5:
                ratio = (both["close_s"] / both["close_f"]).tail(20).median()
            else:
                ratio = 1.0
            add = yf[~yf["date"].isin(old["date"])].copy()
            for c in ["open", "high", "low", "close"]:
                add[c] = add[c] * ratio
            add["source"] = f"Yahoo GC=F × {ratio:.4f}"
            df = pd.concat([old, add]).drop_duplicates("date", keep="last")
        else:
            df = yf
        note("Giá XAU/USD (Yahoo dự phòng)", True, f"{len(df)} dòng, ngày cuối {df['date'].max()}")
        return df
    except Exception as exc:  # noqa: BLE001
        note("Giá XAU/USD (Yahoo dự phòng)", False, exc)
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
    for div in (1e6, 1e3, 1.0):
        y = x / div
        if 50 <= y <= 600:
            return round(y, 2)
    if 5e6 <= x <= 6e7:  # giá theo chỉ, đơn vị đồng
        return round(x * 10 / 1e6, 2)
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
