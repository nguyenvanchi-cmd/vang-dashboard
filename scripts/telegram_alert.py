#!/usr/bin/env python3
"""Cảnh báo Telegram cho Terminal DEMO (chạy bằng GitHub Actions khoảng 10 phút một lần).

Gửi tin khi:
  1. Phiếu tổng đa khung của PAXG/USDT đổi trạng thái (MUA/BÁN mạnh, MUA/BÁN yếu, CHỜ).
     Cách tính giống hệt trang demo: mỗi khung M1–H4 cho MUA/BÁN/CHỜ theo luật EMA + dòng tiền + sức mạnh
     + lực nến + tin cậy ≥ 68% + RSI + khoảng cách tới EMA; phiếu = trọng số × tin cậy.
  2. Còn khoảng 30 phút tới một tin USD mức Cao trong site/data/macro.json.

Cần 2 secret của kho: TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID. Thiếu thì chỉ in ra màn hình (chạy thử).
Trạng thái đã gửi lưu ở data/alert_state.json để không gửi trùng.
Chỉ để tham khảo, không phải tín hiệu giao dịch.
"""
import datetime as dt
import json
import math
import os
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "alert_state.json")
MACRO = os.path.join(ROOT, "site", "data", "macro.json")
VN = dt.timezone(dt.timedelta(hours=7))
SYMBOL = os.environ.get("ALERT_SYMBOL", "PAXGUSDT")
HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
TFS = {"M1": "1m", "M5": "5m", "M15": "15m", "H1": "1h", "H4": "4h"}
VOTE_W = {"H1": 0.25, "M15": 0.25, "M5": 0.2, "H4": 0.2, "M1": 0.1}
RULE = {"conf": 68, "rsiBuy": 68, "rsiSell": 40, "distMin": 0.7, "distMax": 2.5}
CUR_TF = "M15"  # MẠNH chỉ khi khung này cùng hướng (trang demo dùng khung đang xem)
LINK = "https://nguyenvanchi-cmd.github.io/vang-dashboard/demo/"
UA = "vang-dashboard-alert/1.0"


def get_json(path):
    err = None
    for h in HOSTS:
        try:
            with urllib.request.urlopen(urllib.request.Request(h + path, headers={"User-Agent": UA}), timeout=20) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            err = e
    raise RuntimeError(f"Không lấy được {path}: {err}")


def ema(vals, n):
    k, out, e = 2 / (n + 1), [], vals[0]
    for i, v in enumerate(vals):
        e = v * k + e * (1 - k) if i else v
        out.append(e)
    return out


def rsi(vals, n=14):
    up = dn = 0.0
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        u, w = max(d, 0), max(-d, 0)
        if i == 1:
            up, dn = u, w
        else:
            up += (u - up) / n; dn += (w - dn) / n
    return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)


def atr(bars, n=14):
    s = bars[-n - 1:]
    a = sum(max(s[i]["h"] - s[i]["l"], abs(s[i]["h"] - s[i - 1]["c"]), abs(s[i]["l"] - s[i - 1]["c"])) for i in range(1, len(s)))
    return a / max(1, len(s) - 1)


def sgn(x, eps):
    return 0 if abs(x) < eps else (1 if x > 0 else -1)


def analyze(bars):
    bars = bars[-300:]
    c = [b["c"] for b in bars]
    e8, e21 = ema(c, 8), ema(c, 21)
    n, last, A = len(c) - 1, bars[-1], atr(bars) or 1e-9
    trend = 1 if e8[n] > e21[n] and e8[n] >= e8[n - 1] else -1 if e8[n] < e21[n] and e8[n] <= e8[n - 1] else 0
    flow_sum = sum(b["d"] for b in bars[-10:])
    d_scale = (sum(abs(b["d"]) for b in bars[-60:]) / max(1, min(60, len(bars)))) or 1
    flowN = math.tanh(flow_sum / (d_scale * 6))
    powerN = math.tanh((c[n] - c[max(0, n - 5)]) / (A * 1.5))
    deltaN = math.tanh((last["c"] - last["o"]) / (A * 0.5))
    flow, power, delta = sgn(flowN, 0.08), sgn(powerN, 0.08), sgn(deltaN, 0.05)
    r = rsi(c[-120:])
    dist = (c[n] - e8[n]) / A
    d = trend or (1 if flowN + powerN > 0 else -1 if flowN + powerN < 0 else 0)
    agree = sum(1 for x in (flow, power, delta) if x != 0 and x == d)
    conf = round(min(95, 50 + agree * 7 + abs(trend) * 6 + min(10, abs(r - 50) / 2.5)))
    sig, why = "wait", "bốn chỉ số chưa cùng dấu"
    if trend > 0 and flow > 0 and power > 0 and delta > 0:
        if conf < RULE["conf"]: why = f"tin cậy {conf}%"
        elif r >= RULE["rsiBuy"]: why = f"RSI {r:.0f} quá mua"
        elif dist < RULE["distMin"]: why = f"mới cách EMA {dist:.2f} ATR"
        elif dist >= RULE["distMax"]: why = f"quá xa EMA {dist:.2f} ATR"
        else: sig, why = "buy", "đủ điều kiện MUA"
    elif trend < 0 and flow < 0 and power < 0 and delta < 0:
        if conf < RULE["conf"]: why = f"tin cậy {conf}%"
        elif r <= RULE["rsiSell"]: why = f"RSI {r:.0f} quá bán"
        elif -dist < RULE["distMin"]: why = f"mới cách EMA {-dist:.2f} ATR"
        elif -dist >= RULE["distMax"]: why = f"quá xa EMA {-dist:.2f} ATR"
        else: sig, why = "sell", "đủ điều kiện BÁN"
    return {"sig": sig, "conf": conf, "why": why, "rsi": r, "atr": A, "close": c[n]}


def global_vote(all_):
    v = sum(0 if a["sig"] == "wait" else VOTE_W[k] * a["conf"] * (1 if a["sig"] == "buy" else -1) for k, a in all_.items())
    m = abs(v)
    level = "wait" if m < 10 else "weak" if m < 23 else "strong"
    d = "wait" if level == "wait" else ("buy" if v > 0 else "sell")
    if level == "strong" and all_[CUR_TF]["sig"] != d:
        level = "weak"
    return v, d, level


def send(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[chạy thử, chưa có secret Telegram]\n" + text)
        return True
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body), timeout=20) as r:
            ok = json.loads(r.read().decode()).get("ok")
            print("Đã gửi Telegram" if ok else "Telegram trả lỗi")
            return bool(ok)
    except Exception as e:
        print(f"Gửi Telegram lỗi: {type(e).__name__}")  # không in token
        return False


def main():
    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            state = {}
    now = dt.datetime.now(VN)
    changed = False

    # 1. Phiếu tổng
    all_ = {}
    for k, iv in TFS.items():
        raw = get_json(f"/api/v3/klines?symbol={SYMBOL}&interval={iv}&limit=300")
        bars = [{"o": float(x[1]), "h": float(x[2]), "l": float(x[3]), "c": float(x[4]), "d": 2 * float(x[9]) - float(x[5])} for x in raw]
        all_[k] = analyze(bars)
    v, d, level = global_vote(all_)
    key = f"{d}-{level}"
    px = all_["M1"]["close"]
    print(f"{now:%d/%m %H:%M} phiếu {v:+.1f} → {key} · " + " ".join(f"{k}:{a['sig']}/{a['conf']}" for k, a in all_.items()))
    if state.get("vote") is None:
        state["vote"] = key; changed = True  # lần đầu: chỉ ghi nhận, không gửi
    elif key != state["vote"]:
        name = {"buy": "MUA", "sell": "BÁN", "wait": "CHỜ"}[d]
        lv = {"strong": " MẠNH", "weak": " yếu", "wait": ""}[level]
        icon = "🟢" if d == "buy" else "🔴" if d == "sell" else "⚪"
        lines = [f"{icon} <b>PAXG (≈XAU) · Phiếu tổng: {name}{lv}</b> ({v:+.0f})", f"Giá {px:,.2f} · lúc {now:%H:%M} giờ VN", ""]
        lines += [f"{k}: {({'buy': 'MUA', 'sell': 'BÁN', 'wait': 'CHỜ'})[a['sig']]} {a['conf']}% · {a['why']}" for k, a in all_.items()]
        lines += ["", f"Trước đó: {state['vote']}", f'<a href="{LINK}">Mở Terminal DEMO</a> · Chỉ để tham khảo, không phải tín hiệu giao dịch.']
        if send("\n".join(lines)):
            state["vote"] = key; changed = True

    # 2. Tin mạnh sắp ra
    try:
        cal = json.load(open(MACRO, encoding="utf-8")).get("calendar", [])
    except Exception:
        cal = []
    sent = set(state.get("news_sent", []))
    ts = now.timestamp()
    for e in cal:
        mins = (e["t"] - ts) / 60
        k = f"{e['t']}-{e['cur']}-{e['title']}"
        if e["imp"] == "high" and e["cur"] == "USD" and 0 < mins <= 40 and k not in sent:
            at = dt.datetime.fromtimestamp(e["t"], VN)
            name = e.get("vi") or e["title"]
            extra = " · ".join(x for x in [f"dự báo {e['forecast']}" if e.get("forecast") else "", f"kỳ trước {e['previous']}" if e.get("previous") else ""] if x)
            msg = f"⚠️ <b>Tin mạnh USD lúc {at:%H:%M}</b> (còn {int(mins)} phút)\n{name} ({e['title']})" + (f"\n{extra}" if extra else "") + "\nVàng thường giật mạnh quanh giờ tin: cân nhắc đứng ngoài hoặc giảm khối lượng."
            if send(msg):
                sent.add(k); changed = True
    keep = [k for k in sent if int(k.split("-")[0]) > ts - 7 * 86400]
    if sorted(keep) != sorted(state.get("news_sent", [])):
        state["news_sent"] = sorted(keep); changed = True

    if changed:
        state["updated"] = now.isoformat(timespec="minutes")
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
