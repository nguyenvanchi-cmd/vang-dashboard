#!/usr/bin/env python3
"""Phân tích định lượng và học máy trên lịch sử giá vàng, xuất JSON cho website.

Đầu vào: data/xauusd_daily.csv (bắt buộc), data/usd_vnd.csv, data/domestic.csv, data/claude_daily.json.
Đầu ra: site/data/*.json và site/data/xauusd_daily.csv.

Mọi kết quả là thống kê quá khứ, không bảo đảm cho tương lai.
"""
import json
import math
import os
import shutil
import datetime as dt

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "site", "data")
os.makedirs(OUT_DIR, exist_ok=True)
VN = dt.timezone(dt.timedelta(hours=7))
NOW = dt.datetime.now(VN)
OZ_PER_LUONG = 1.20565
WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu"]
MONTHS = [f"Th{m}" for m in range(1, 13)]


def r(x, n=2):
    if x is None:
        return None
    try:
        if isinstance(x, (np.floating, float)) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def dump(name, obj):
    with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ chỉ báo
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def add_indicators(df):
    c = df["close"]
    df["ret1"] = c.pct_change()
    df["ema20"], df["ema50"], df["ema200"] = ema(c, 20), ema(c, 50), ema(c, 200)
    df["rsi14"] = rsi(c)
    macd = ema(c, 12) - ema(c, 26)
    df["macd"], df["macd_sig"] = macd, ema(macd, 9)
    df["macd_hist"] = df["macd"] - df["macd_sig"]
    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(),
                    (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["vol20"] = np.log(c).diff().rolling(20).std() * math.sqrt(252)
    df["hi252"] = c.rolling(252, min_periods=60).max()
    df["lo252"] = c.rolling(252, min_periods=60).min()
    df["ath"] = c.cummax()
    down = (df["ret1"] < 0).astype(int)
    df["down_streak"] = down.groupby((down != down.shift()).cumsum()).cumsum() * down
    return df


# ------------------------------------------------------------------ tổng quan
def summary(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    c = df["close"]

    def chg(k):
        return r((last["close"] / c.iloc[-1 - k] - 1) * 100) if len(c) > k else None

    year_start = df[df["date"] < f"{last['date'][:4]}-01-01"]
    ytd = r((last["close"] / year_start["close"].iloc[-1] - 1) * 100) if len(year_start) else None
    ath_idx = c.idxmax()
    if last["close"] > last["ema50"] > last["ema200"]:
        regime = "Xu hướng tăng"
    elif last["close"] < last["ema50"] < last["ema200"]:
        regime = "Xu hướng giảm"
    else:
        regime = "Giằng co"
    rsi_v = float(last["rsi14"])
    rsi_zone = "Quá bán" if rsi_v < 30 else "Quá mua" if rsi_v > 70 else "Trung tính"
    return {
        "date": last["date"], "close": r(last["close"]), "open": r(last["open"]),
        "high": r(last["high"]), "low": r(last["low"]),
        "chg1d": r((last["close"] / prev["close"] - 1) * 100), "chg1d_abs": r(last["close"] - prev["close"]),
        "chg1w": chg(5), "chg1m": chg(21), "chg3m": chg(63), "chg1y": chg(252), "ytd": ytd,
        "hi52": r(last["hi252"]), "lo52": r(last["lo252"]),
        "ath": r(c.max()), "ath_date": df.loc[ath_idx, "date"],
        "dd_from_ath": r((last["close"] / c.max() - 1) * 100),
        "ema20": r(last["ema20"]), "ema50": r(last["ema50"]), "ema200": r(last["ema200"]),
        "dist_ema200": r((last["close"] / last["ema200"] - 1) * 100),
        "rsi14": r(rsi_v, 1), "rsi_zone": rsi_zone,
        "macd": r(last["macd"]), "macd_sig": r(last["macd_sig"]), "macd_hist": r(last["macd_hist"]),
        "vol20": r(last["vol20"] * 100, 1), "atr14": r(last["atr14"]),
        "regime": regime, "down_streak": int(last["down_streak"]),
        "first_date": df["date"].iloc[0], "rows": int(len(df)),
    }


# ------------------------------------------------------------------ theo mùa
def seasonality(df, start=None):
    d = df if start is None else df[df["date"] >= start]
    d = d.dropna(subset=["ret1"])
    dts = pd.to_datetime(d["date"])
    rets = d["ret1"] * 100
    wd = []
    for i, name in enumerate(WEEKDAYS):
        x = rets[dts.dt.weekday == i]
        if len(x) < 20:
            continue
        t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if x.std(ddof=1) > 0 else 0
        wd.append({"label": name, "mean": r(x.mean(), 3), "hit": r((x > 0).mean() * 100, 1),
                   "n": int(len(x)), "t": r(t)})
    m = df.set_index(pd.to_datetime(df["date"]))["close"].resample("ME").last()
    if start is not None:
        m = m[m.index >= pd.Timestamp(start)]
    mr = m.pct_change().dropna() * 100
    # bỏ tháng hiện tại nếu chưa kết thúc
    if len(mr) and mr.index[-1].strftime("%Y-%m") == NOW.strftime("%Y-%m"):
        mr = mr.iloc[:-1]
    mo = []
    for k in range(1, 13):
        x = mr[mr.index.month == k]
        if len(x) < 3:
            continue
        t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if x.std(ddof=1) > 0 else 0
        mo.append({"label": MONTHS[k - 1], "mean": r(x.mean(), 2), "hit": r((x > 0).mean() * 100, 1),
                   "n": int(len(x)), "t": r(t)})
    return {"weekday": wd, "month": mo, "from": str(d["date"].iloc[0]), "to": str(d["date"].iloc[-1])}


# ------------------------------------------------------------------ nghiên cứu sự kiện
HORIZONS = [1, 5, 20, 60]


def forward_returns(df):
    c = df["close"].values
    out = {}
    for h in HORIZONS:
        fr = np.full(len(c), np.nan)
        fr[:-h] = c[h:] / c[:-h] - 1
        out[h] = fr * 100
    return out


def decluster(mask, gap=5):
    idx = np.flatnonzero(mask)
    keep, last = [], -10**9
    for i in idx:
        if i - last > gap:
            keep.append(i)
            last = i
    m = np.zeros(len(mask), dtype=bool)
    m[keep] = True
    return m


def event_study(df):
    fr = forward_returns(df)
    c = df["close"]
    conds = [
        ("drop2", "Phiên giảm từ 2% trở lên", (df["ret1"] <= -0.02).values, True),
        ("drop3", "Phiên giảm từ 3% trở lên", (df["ret1"] <= -0.03).values, True),
        ("down3", "3 phiên giảm liên tiếp", (df["down_streak"] == 3).values, True),
        ("rsi30", "RSI(14) vừa xuống dưới 30", ((df["rsi14"] < 30) & (df["rsi14"].shift() >= 30)).values, True),
        ("low52", "Đóng cửa thấp nhất 52 tuần", ((c <= df["lo252"]) & df["lo252"].notna()).values, True),
        ("rise3", "Phiên tăng từ 3% trở lên", (df["ret1"] >= 0.03).values, True),
        ("below200", "Giá nằm dưới EMA200", (c < df["ema200"]).values, False),
        ("above200", "Giá nằm trên EMA200", (c > df["ema200"]).values, False),
        ("dd20", "Giảm từ 20% trở lên so với đỉnh lịch sử", (c / df["ath"] - 1 <= -0.20).values, False),
    ]
    valid = np.arange(len(df)) >= 200
    base = {}
    for h in HORIZONS:
        x = fr[h][valid]
        x = x[~np.isnan(x)]
        base[h] = {"mean": r(x.mean()), "median": r(np.median(x)), "hit": r((x > 0).mean() * 100, 1)}
    rows = []
    for key, label, mask, is_event in conds:
        mask = mask & valid
        active = bool(mask[-1])
        if is_event:
            mask = decluster(mask)
        stats = {}
        for h in HORIZONS:
            x = fr[h][mask]
            x = x[~np.isnan(x)]
            if len(x) < 5:
                stats[str(h)] = None
                continue
            sd = x.std(ddof=1)
            t = (x.mean() - (base[h]["mean"] or 0)) / (sd / math.sqrt(len(x))) if sd > 0 else 0
            stats[str(h)] = {"mean": r(x.mean()), "median": r(np.median(x)), "hit": r((x > 0).mean() * 100, 1),
                             "n": int(len(x)), "t": r(t)}
        rows.append({"key": key, "label": label, "type": "event" if is_event else "state",
                     "active": active, "count": int(mask.sum()), "stats": stats})
    return {"baseline": {str(h): base[h] for h in HORIZONS}, "rows": rows, "horizons": HORIZONS}


# ------------------------------------------------------------------ kiểm định chiến lược
def perf(eq, pos, years):
    rets = eq.pct_change().dropna()
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    vol = rets.std() * math.sqrt(252)
    sharpe = rets.mean() / rets.std() * math.sqrt(252) if rets.std() > 0 else 0
    dd = (eq / eq.cummax() - 1).min()
    switches = pos.diff().abs().sum()
    return {"cagr": r(cagr * 100), "vol": r(vol * 100), "sharpe": r(sharpe), "maxdd": r(dd * 100),
            "exposure": r(pos.mean() * 100, 1), "switches_per_year": r(switches / years, 1),
            "total": r((eq.iloc[-1] / eq.iloc[0] - 1) * 100, 1)}


def backtests(df):
    d = df.iloc[200:].reset_index(drop=True)
    ret = d["close"].pct_change().fillna(0)
    years = len(d) / 252
    rules = {
        "buy_hold": ("Mua và giữ", pd.Series(1.0, index=d.index)),
        "ema200": ("Chỉ giữ khi giá trên EMA200", (d["close"] > d["ema200"]).astype(float)),
        "ema50_200": ("Chỉ giữ khi EMA50 trên EMA200", (d["ema50"] > d["ema200"]).astype(float)),
        "macd": ("Chỉ giữ khi MACD trên đường trung bình", (d["macd"] > d["macd_sig"]).astype(float)),
    }
    costs = {"world": 0.0005, "vn": 0.015}
    out, curves = [], {}
    step = max(1, len(d) // 600)
    for key, (label, sig) in rules.items():
        pos = sig.shift().fillna(0)  # quyết định ở phiên trước, áp dụng cho phiên sau
        row = {"key": key, "label": label}
        for ck, cv in costs.items():
            trade = pos.diff().abs().fillna(pos.iloc[0])
            eq = (1 + pos * ret - trade * cv).cumprod()
            row[ck] = perf(eq, pos, years)
            if ck == "world":
                curves[key] = [[d["date"].iloc[i], r(eq.iloc[i], 4)] for i in range(0, len(d), step)]
                curves[key].append([d["date"].iloc[-1], r(eq.iloc[-1], 4)])
        out.append(row)
    return {"from": d["date"].iloc[0], "to": d["date"].iloc[-1], "rows": out, "curves": curves,
            "costs": {"world": "0,05% mỗi lần đổi trạng thái (thị trường thế giới)",
                      "vn": "1,5% mỗi lần đổi trạng thái (tương đương chênh mua–bán 3% ở tiệm vàng)"}}


def accumulation(df, years_back):
    """So sánh Mua nền hằng tháng với chiến dịch 70–20–10 của kênh."""
    d = df.copy()
    d["dt"] = pd.to_datetime(d["date"])
    start = d["dt"].iloc[-1] - pd.DateOffset(years=years_back)
    d = d[d["dt"] >= start].reset_index(drop=True)
    if len(d) < 200:
        return None
    first_days = d.groupby(d["dt"].dt.to_period("M")).head(1).index.tolist()
    budget = 1000.0
    dca_oz = 0.0
    c_oz, pot_than, pot_cho = 0.0, 0.0, 0.0
    events_than = events_cho = 0
    for i in first_days:
        px = d.loc[i, "close"]
        dca_oz += budget / px
        c_oz += 0.7 * budget / px
        pot_than += 0.2 * budget
        pot_cho += 0.1 * budget
        if d.loc[i, "close"] > d.loc[i, "ema50"] > d.loc[i, "ema200"] and pot_than > 0:
            c_oz += pot_than / px
            pot_than = 0.0
            events_than += 1
        if d.loc[i, "close"] / d.loc[i, "hi252"] - 1 <= -0.15 and pot_cho > 0:
            c_oz += pot_cho / px
            pot_cho = 0.0
            events_cho += 1
    invested = budget * len(first_days)
    last = d["close"].iloc[-1]
    cash_left = pot_than + pot_cho
    c_spent = invested - cash_left

    def res(label, oz, spent, cash):
        value = oz * last + cash
        return {"label": label, "oz": r(oz, 3), "avg_cost": r(spent / oz if oz else None),
                "value": r(value), "invested": r(invested), "ret": r((value / invested - 1) * 100, 1),
                "cash_left": r(cash)}

    return {"years": years_back, "months": len(first_days), "from": d["date"].iloc[0], "to": d["date"].iloc[-1],
            "last_close": r(last),
            "rows": [res("Mua nền đều mỗi tháng (100%)", dca_oz, invested, 0.0),
                     res("Chiến dịch 70–20–10", c_oz, c_spent, cash_left)],
            "events": {"mua_xac_nhan": events_than, "quy_cho": events_cho}}


# ------------------------------------------------------------------ học máy
FEATURES = ["r1", "r5", "r10", "r20", "r60", "d_ema20", "d_ema50", "d_ema200", "rsi14", "macd_n",
            "atr_n", "vol20", "dd52", "pos52", "down_streak", "dow", "month"]
FEATURE_VI = {"r1": "Lợi nhuận 1 phiên", "r5": "Lợi nhuận 5 phiên", "r10": "Lợi nhuận 10 phiên",
              "r20": "Lợi nhuận 20 phiên", "r60": "Lợi nhuận 60 phiên", "d_ema20": "Khoảng cách tới EMA20",
              "d_ema50": "Khoảng cách tới EMA50", "d_ema200": "Khoảng cách tới EMA200", "rsi14": "RSI(14)",
              "macd_n": "Histogram MACD", "atr_n": "Biên độ ATR", "vol20": "Biến động 20 phiên",
              "dd52": "Cách đỉnh 52 tuần", "pos52": "Vị trí trong biên 52 tuần", "down_streak": "Chuỗi phiên giảm",
              "dow": "Thứ trong tuần", "month": "Tháng"}
H = 5


def ml_features(df):
    c = df["close"]
    X = pd.DataFrame(index=df.index)
    for k in (1, 5, 10, 20, 60):
        X[f"r{k}"] = c.pct_change(k)
    for n in (20, 50, 200):
        X[f"d_ema{n}"] = c / df[f"ema{n}"] - 1
    X["rsi14"] = df["rsi14"]
    X["macd_n"] = df["macd_hist"] / c
    X["atr_n"] = df["atr14"] / c
    X["vol20"] = df["vol20"]
    X["dd52"] = c / df["hi252"] - 1
    X["pos52"] = (c - df["lo252"]) / (df["hi252"] - df["lo252"]).replace(0, np.nan)
    X["down_streak"] = df["down_streak"]
    dts = pd.to_datetime(df["date"])
    X["dow"] = dts.dt.weekday
    X["month"] = dts.dt.month
    y = (c.shift(-H) > c).astype(float)
    y[c.shift(-H).isna()] = np.nan
    fwd = (c.shift(-H) / c - 1)
    return X, y, fwd


def machine_learning(df):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X, y, fwd = ml_features(df)
    ok = X.notna().all(axis=1)
    years = pd.to_datetime(df["date"]).dt.year
    first_year = int(years[ok].min())
    last_year = int(years.max())
    test_years = [yy for yy in range(first_year + 6, last_year + 1)]
    if not test_years:
        return None

    def models():
        return {
            "logit": make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)),
            "gbm": HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                                  min_samples_leaf=50, l2_regularization=1.0, random_state=7),
        }

    preds = {"logit": pd.Series(np.nan, index=df.index), "gbm": pd.Series(np.nan, index=df.index)}
    base_pred = pd.Series(np.nan, index=df.index)
    last_fold = None
    for yy in test_years:
        test = ok & y.notna() & (years == yy)
        if test.sum() < 20:
            continue
        test_start = test.idxmax()
        train = ok & y.notna() & (df.index < test_start - H)  # bỏ H phiên giáp ranh để tránh rò rỉ nhãn
        if train.sum() < 750:
            continue
        maj = float(y[train].mean() >= 0.5)
        base_pred[test] = maj
        for name, m in models().items():
            m.fit(X[train], y[train])
            preds[name][test] = m.predict_proba(X[test])[:, 1]
            if name == "gbm":
                last_fold = (m, X[test], y[test])

    mask = preds["gbm"].notna() & y.notna()
    if mask.sum() < 200:
        return None
    yt = y[mask]
    res_models = {}
    for name, p in preds.items():
        pp = p[mask]
        hi = (pp >= 0.6) | (pp <= 0.4)
        res_models[name] = {
            "accuracy": r(accuracy_score(yt, pp >= 0.5) * 100, 1),
            "auc": r(roc_auc_score(yt, pp), 3),
            "brier": r(brier_score_loss(yt, pp), 4),
            "confident_share": r(hi.mean() * 100, 1),
            "confident_accuracy": r(accuracy_score(yt[hi], pp[hi] >= 0.5) * 100, 1) if hi.sum() > 30 else None,
        }
    baseline_acc = r(accuracy_score(yt, base_pred[mask]) * 100, 1)
    best = max(res_models, key=lambda k: res_models[k]["auc"] or 0)

    per_year = []
    for yy in test_years:
        mm = mask & (years == yy)
        if mm.sum() < 20:
            continue
        per_year.append({"year": int(yy), "acc": r(accuracy_score(y[mm], preds[best][mm] >= 0.5) * 100, 1),
                         "base": r(accuracy_score(y[mm], base_pred[mm]) * 100, 1), "n": int(mm.sum())})

    # Chiến lược thử: chỉ giữ vàng khi mô hình cho xác suất tăng > 50% (giữ 5 phiên, đánh giá theo ngày)
    d = df.loc[mask[mask].index]
    p = preds[best][mask]
    daily_ret = df["close"].pct_change().shift(-1)[mask].fillna(0)  # lợi nhuận phiên kế tiếp
    pos = (p > 0.5).astype(float)
    trade = pos.diff().abs().fillna(pos.iloc[0])
    eq_model = (1 + pos * daily_ret - trade * 0.0005).cumprod()
    eq_bh = (1 + daily_ret).cumprod()
    yrs = len(d) / 252
    strat = {"model_cagr": r(((eq_model.iloc[-1]) ** (1 / yrs) - 1) * 100),
             "bh_cagr": r(((eq_bh.iloc[-1]) ** (1 / yrs) - 1) * 100),
             "model_maxdd": r((eq_model / eq_model.cummax() - 1).min() * 100),
             "bh_maxdd": r((eq_bh / eq_bh.cummax() - 1).min() * 100),
             "exposure": r(pos.mean() * 100, 1)}

    # Mức quan trọng của biến (hoán vị trên giai đoạn kiểm tra cuối)
    importance = []
    if last_fold is not None:
        m, Xt, yt_last = last_fold
        if best == "gbm":
            pi = permutation_importance(m, Xt, yt_last, n_repeats=5, random_state=7, scoring="roc_auc")
            vals = pi.importances_mean
        else:
            lm = models()["logit"].fit(X[ok & y.notna()], y[ok & y.notna()])
            vals = np.abs(lm[-1].coef_[0])
        importance = sorted([{"feature": FEATURE_VI[f], "value": r(v, 4)} for f, v in zip(FEATURES, vals)],
                            key=lambda z: -(z["value"] or 0))[:10]

    # Dự báo hiện tại: huấn luyện trên toàn bộ dữ liệu có nhãn
    full = ok & y.notna()
    m = models()[best].fit(X[full], y[full])
    now_p = float(m.predict_proba(X[ok].iloc[[-1]])[:, 1][0])

    auc = res_models[best]["auc"] or 0.5
    acc = res_models[best]["accuracy"] or 0
    if acc <= (baseline_acc or 0) or auc < 0.52:
        verdict = ("Mô hình không dự báo tốt hơn cách đoán đơn giản: hướng đi 5 phiên tới của vàng gần như ngẫu nhiên "
                   "với các dữ kiện kỹ thuật này. Không nên dựa vào con số xác suất để mua bán.")
        strength = "yếu"
    elif auc < 0.53:
        verdict = ("Mô hình chỉ nhỉnh hơn tung đồng xu một chút. Không nên dựa vào con số xác suất để mua bán.")
        strength = "yếu"
    elif auc < 0.58:
        verdict = ("Mô hình có chút khả năng phân biệt nhưng yếu và không ổn định qua các năm. "
                   "Chỉ dùng như một dữ kiện tham khảo bên cạnh phân tích 3 tầng.")
        strength = "vừa"
    else:
        verdict = ("Mô hình phân biệt khá tốt trên dữ liệu quá khứ, nhưng thị trường thay đổi nên vẫn cần thận trọng.")
        strength = "khá"

    return {"horizon": H, "best": best, "best_label": "Gradient boosting" if best == "gbm" else "Hồi quy logistic",
            "models": res_models, "baseline_acc": baseline_acc, "n_test": int(mask.sum()),
            "test_from": str(df.loc[mask[mask].index[0], "date"]), "test_to": str(df.loc[mask[mask].index[-1], "date"]),
            "per_year": per_year, "strategy": strat, "importance": importance,
            "now": {"date": str(df["date"].iloc[-1]), "p_up": r(now_p * 100, 1)},
            "verdict": verdict, "strength": strength, "accuracy": acc, "auc": auc}


# ------------------------------------------------------------------ nhận định rút ra
def vn(x, d=2, sign=False):
    """Định dạng số kiểu Việt Nam: dấu chấm phân cách hàng nghìn, dấu phẩy thập phân."""
    if x is None:
        return "—"
    s = f"{x:+,.{d}f}" if sign else f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def insights(ev, bt, acc_res, ml):
    out = []
    rows = {x["key"]: x for x in ev["rows"]}
    base20 = ev["baseline"]["20"]

    for key in ("drop3", "rsi30", "low52", "down3"):
        x = rows.get(key)
        if not x or not x["stats"].get("20"):
            continue
        s = x["stats"]["20"]
        diff = (s["mean"] or 0) - (base20["mean"] or 0)
        tval = abs(s["t"] or 0)
        strength = "mạnh" if tval >= 2.5 else "vừa" if tval >= 1.5 else "yếu"
        word = "cao hơn" if diff > 0 else "thấp hơn"
        out.append({"title": x["label"] + (" — đang xảy ra" if x["active"] else ""), "active": x["active"],
                    "strength": strength,
                    "text": (f"Trong {s['n']} lần như vậy, 20 phiên sau giá thay đổi trung bình {vn(s['mean'], 2, True)}% "
                             f"(tỷ lệ tăng {vn(s['hit'], 0)}%), {word} mức bình thường {vn(base20['mean'], 2, True)}% "
                             f"khoảng {vn(abs(diff), 2)} điểm %.")})
    bh = next(z for z in bt["rows"] if z["key"] == "buy_hold")
    tf = next(z for z in bt["rows"] if z["key"] == "ema200")
    out.append({"title": "Lọc xu hướng EMA200 và chi phí mua bán", "active": False, "strength": "mạnh",
                "text": (f"Chỉ giữ vàng khi giá trên EMA200 cho mức sụt giảm sâu nhất {vn(tf['world']['maxdd'], 0)}% "
                         f"so với {vn(bh['world']['maxdd'], 0)}% của mua và giữ; lợi nhuận năm {vn(tf['world']['cagr'], 1)}% "
                         f"so với {vn(bh['world']['cagr'], 1)}%. Nhưng nếu mỗi lần mua hoặc bán mất 1,5% như ở tiệm vàng, "
                         f"lợi nhuận năm chỉ còn {vn(tf['vn']['cagr'], 1)}%: đổi trạng thái liên tục không hợp với vàng vật chất.")})
    if acc_res:
        a, b = acc_res["rows"]
        diff = (b["avg_cost"] or 0) - (a["avg_cost"] or 0)
        out.append({"title": f"Mua nền đều so với chiến dịch 70–20–10 ({acc_res['years']} năm)", "active": False,
                    "strength": "vừa",
                    "text": (f"Cùng 1.000 USD mỗi tháng: giá vốn bình quân của chiến dịch 70–20–10 là "
                             f"{vn(b['avg_cost'], 0)} USD/oz, so với {vn(a['avg_cost'], 0)} USD/oz khi mua đều 100% "
                             f"({'cao hơn' if diff > 0 else 'thấp hơn'} {vn(abs(diff), 0)} USD/oz). "
                             f"Giá trị cuối kỳ {vn(b['value'], 0)} USD so với {vn(a['value'], 0)} USD.")})
    if ml:
        out.append({"title": "Học máy dự báo 5 phiên tới", "active": False, "strength": ml["strength"],
                    "text": (f"Kiểm tra trượt theo từng năm trên {vn(ml['n_test'], 0)} phiên: độ chính xác "
                             f"{vn(ml['accuracy'], 1)}%, so với {vn(ml['baseline_acc'], 1)}% nếu luôn đoán theo xu hướng chung; "
                             f"AUC {vn(ml['auc'], 3)}. " + ml["verdict"])})
    return out


# ------------------------------------------------------------------ trong nước
def domestic(df):
    out = {"latest": [], "usd_vnd": None, "premium": None, "history": []}
    fx = pd.read_csv(os.path.join(DATA_DIR, "usd_vnd.csv"), dtype={"date": str}) \
        if os.path.exists(os.path.join(DATA_DIR, "usd_vnd.csv")) else None
    dom = pd.read_csv(os.path.join(DATA_DIR, "domestic.csv"), dtype={"date": str}) \
        if os.path.exists(os.path.join(DATA_DIR, "domestic.csv")) else None
    claude = load_claude()
    if fx is not None and len(fx):
        f = fx.iloc[-1]
        out["usd_vnd"] = {"date": f["date"], "sell": r(f["sell"], 0), "source": f["source"]}
    latest_rows, latest_date, src = [], None, None
    if dom is not None and len(dom):
        latest_date = dom["date"].max()
        sub = dom[dom["date"] == latest_date]
        latest_rows = [{"brand": x["brand"], "product": x["product"], "buy": r(x["buy"]), "sell": r(x["sell"]),
                        "time": f"{x['time']} {latest_date[8:10]}/{latest_date[5:7]}"} for _, x in sub.iterrows()]
        src = "Tự động từ website doanh nghiệp"
    if claude and claude.get("gia_trong_nuoc") and (latest_date is None or claude.get("ngay", "") >= latest_date):
        latest_rows = [{"brand": x.get("thuong_hieu"), "product": x.get("loai"), "buy": x.get("mua"),
                        "sell": x.get("ban"), "time": x.get("thoi_diem")} for x in claude["gia_trong_nuoc"]]
        src = "Nhận định hằng ngày của Claude"
        if claude.get("usd_vnd") and not out["usd_vnd"]:
            out["usd_vnd"] = {"date": claude.get("ngay"), "sell": claude["usd_vnd"], "source": "Vietcombank (Claude)"}
    out["latest"] = latest_rows
    out["source"] = src
    last_close = float(df["close"].iloc[-1])
    sjc = next((x for x in latest_rows if x["product"] == "Miếng SJC" and x["brand"] == "SJC"), None) \
        or next((x for x in latest_rows if x["product"] == "Miếng SJC"), None)
    world_px, world_date = last_close, str(df["date"].iloc[-1])
    world_note = f"Theo giá đóng cửa {world_date[8:10]}/{world_date[5:7]} ({df['source'].iloc[-1]})"
    try:
        cx = float((claude or {}).get("xau_usd") or 0)
        if 200 < cx < 20000 and str(claude.get("ngay", "")) >= world_date:
            world_px, world_date = cx, str(claude["ngay"])
            world_note = f"Theo giá giao ngay {vn(cx, 2)} USD/oz Claude ghi nhận sáng {world_date[8:10]}/{world_date[5:7]}"
    except Exception:  # noqa: BLE001
        pass
    if out["usd_vnd"] and out["usd_vnd"]["sell"] and sjc:
        world = world_px * out["usd_vnd"]["sell"] * OZ_PER_LUONG / 1e6
        out["premium"] = {"world_vnd": r(world), "sjc_sell": sjc["sell"], "sjc_buy": sjc["buy"],
                          "prem_sell": r(sjc["sell"] - world), "prem_buy": r(sjc["buy"] - world),
                          "world_date": world_date, "world_usd": r(world_px), "world_note": world_note}
    # lịch sử chênh lệch: ghép giá SJC hằng ngày với giá thế giới và tỷ giá
    if dom is not None and fx is not None and len(dom):
        try:
            s = dom[(dom["brand"] == "SJC") & (dom["product"] == "Miếng SJC")][["date", "sell"]].copy()
            fxs = fx[["date", "sell"]].rename(columns={"sell": "fx"}).copy()
            s["dt"], fxs["dt"] = pd.to_datetime(s["date"]), pd.to_datetime(fxs["date"])
            m = pd.merge_asof(s.sort_values("dt"), fxs[["dt", "fx"]].sort_values("dt"), on="dt")
            px = df[["date", "close"]].copy()
            px["dt"] = pd.to_datetime(px["date"])
            m = pd.merge_asof(m.sort_values("dt"), px[["dt", "close"]].sort_values("dt"), on="dt")
            m["world"] = m["close"] * m["fx"] * OZ_PER_LUONG / 1e6
            m["prem"] = m["sell"] - m["world"]
            out["history"] = [[x["date"], r(x["sell"]), r(x["world"]), r(x["prem"])]
                              for _, x in m.dropna(subset=["prem"]).iterrows()]
        except Exception as exc:  # noqa: BLE001
            print("Lỗi lịch sử chênh lệch:", exc)
    return out


def load_claude():
    p = os.path.join(DATA_DIR, "claude_daily.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ chạy
def main():
    path = os.path.join(DATA_DIR, "xauusd_daily.csv")
    meta = {"built_at": NOW.isoformat(timespec="seconds"), "ok": False}
    fs = os.path.join(DATA_DIR, "fetch_status.json")
    if os.path.exists(fs):
        with open(fs, encoding="utf-8") as f:
            meta["fetch"] = json.load(f)
    if not os.path.exists(path):
        meta["error"] = "Chưa có dữ liệu giá XAU/USD."
        dump("meta.json", meta)
        return
    df = pd.read_csv(path, dtype={"date": str}).dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    for c in ["open", "high", "low"]:
        df[c] = df[c].fillna(df["close"])
    df = add_indicators(df)

    dump("prices.json", {"cols": ["t", "o", "h", "l", "c"],
                         "rows": [[t, r(o), r(h), r(l), r(c)] for t, o, h, l, c in
                                  df[["date", "open", "high", "low", "close"]].itertuples(index=False)],
                         "source": str(df["source"].iloc[-1]) if "source" in df else ""})
    shutil.copy(path, os.path.join(OUT_DIR, "xauusd_daily.csv"))
    summ = summary(df)
    dump("summary.json", summ)

    # Thống kê dùng dữ liệu từ năm 2000 (dữ liệu ngày đầy đủ, liên tục); biểu đồ vẫn hiện toàn bộ lịch sử.
    dq = df[df["date"] >= "2000-01-01"].reset_index(drop=True)
    if len(dq) < 2000:
        dq = df
    ev = event_study(dq)
    bt = backtests(dq)
    acc10 = accumulation(dq, 10)
    acc20 = accumulation(dq, 20)
    seas = {"all": seasonality(dq), "y10": seasonality(dq, str(int(dq["date"].iloc[-1][:4]) - 10) + "-01-01")}
    summ["stats_from"] = dq["date"].iloc[0]
    summ["stats_rows"] = int(len(dq))
    dump("summary.json", summ)
    try:
        ml = machine_learning(dq)
    except Exception as exc:  # noqa: BLE001
        print("ML lỗi:", exc)
        ml = None
    dump("quant.json", {"events": ev, "backtest": bt, "accumulation": [a for a in (acc10, acc20) if a],
                        "seasonality": seas, "insights": insights(ev, bt, acc10, ml)})
    dump("ml.json", ml or {})
    dump("domestic.json", domestic(df))
    claude = load_claude()
    dump("claude.json", claude or {})
    meta.update({"ok": True, "last_date": summ["date"], "rows": summ["rows"], "first_date": summ["first_date"],
                 "price_source": str(df["source"].iloc[-1]) if "source" in df else ""})
    dump("meta.json", meta)
    print("Xong:", meta)


if __name__ == "__main__":
    main()
