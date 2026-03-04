"""
🤖 ZeusX Monitor Bot — 24/7 моніторинг на Railway
Токени зберігаються в Environment Variables (не в коді!)
"""
import json, time, re, urllib.request, urllib.error, os, base64

# ═══════════ КОНФІГ ЧЕРЕЗ ENV VARIABLES ═══════════
# В Railway: Settings → Variables → додай ці змінні
ZEUSX_COOKIE  = os.environ.get("ZEUSX_COOKIE", "")
MY_ZEUSX_ID   = os.environ.get("MY_ZEUSX_ID", "282297")
TG_TOKEN      = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID    = os.environ.get("TG_CHAT_ID", "")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "60"))
# ══════════════════════════════════════════════════

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
ZEUSX_BASE = "https://api.zeusx.com/v1"
STATE_FILE = "monitor_state.json"

def _parse_cookie(s):
    d = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d

def _access_token():
    return _parse_cookie(ZEUSX_COOKIE).get("access_token", "")

def _zx_req(method, path, body=None):
    global ZEUSX_COOKIE
    token = _access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Origin": "https://zeusx.com",
        "Referer": "https://zeusx.com/",
    }
    data = json.dumps(body).encode() if body else None
    try:
        req = urllib.request.Request(ZEUSX_BASE + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            if _refresh_token():
                return _zx_req(method, path, body)
        return None, f"HTTP {e.code}"
    except Exception as ex:
        return None, str(ex)

def _refresh_token():
    global ZEUSX_COOKIE
    rt = _parse_cookie(ZEUSX_COOKIE).get("refresh_token", "")
    if not rt: return False
    try:
        body = json.dumps({"refresh_token": rt}).encode()
        req = urllib.request.Request(
            "https://api.zeusx.com/v1/auth/refresh-token", data=body,
            headers={"Content-Type": "application/json", "User-Agent": UA, "Origin": "https://zeusx.com"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode())
        new_t = (d.get("data") or {}).get("access_token") or d.get("access_token")
        new_r = (d.get("data") or {}).get("refresh_token") or d.get("refresh_token")
        if new_t:
            ZEUSX_COOKIE = re.sub(r"access_token=[^;]+", "access_token=" + new_t, ZEUSX_COOKIE)
            if new_r:
                ZEUSX_COOKIE = re.sub(r"refresh_token=[^;]+", "refresh_token=" + new_r, ZEUSX_COOKIE)
            print("✅ Токен оновлено!", flush=True)
            return True
    except Exception as ex:
        print(f"⚠ refresh: {ex}", flush=True)
    return False

def tg_send(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("⚠ TG не налаштовано", flush=True); return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        print(f"📨 TG: {text[:60]}", flush=True)
    except Exception as ex:
        print(f"⚠ TG: {ex}", flush=True)

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            return json.loads(open(STATE_FILE).read())
    except: pass
    return {"sale_ids": [], "msg_keys": [], "initialized": False}

def save_state(state):
    try:
        json.dump(state, open(STATE_FILE, "w"))
    except: pass

def get_all_listings():
    all_sales = []
    for page in range(0, 100):
        d, err = _zx_req("GET", f"/offer/my-sales-listing?pageIndex={page}")
        if err or not d: break
        sales = (d.get("data") or {}).get("sales", [])
        if not sales: break
        all_sales.extend(sales)
        total = (d.get("data") or {}).get("pagination", {}).get("totalRecords", 0)
        if total and len(all_sales) >= total: break
        if len(sales) < 12: break
        time.sleep(0.3)
    return all_sales

def check_sales(listings, state):
    known = set(state.get("sale_ids", []))
    new_sales = []
    for lot in listings:
        for p in (lot.get("offer_purchases") or []):
            tid = p.get("transaction_id") or p.get("id")
            if not tid: continue
            if not state["initialized"]:
                known.add(tid); continue
            if tid not in known:
                known.add(tid)
                new_sales.append({
                    "title": (lot.get("title") or "")[:60],
                    "buyer": p.get("buyer_display_name") or "?",
                    "price": float(p.get("listed_price") or 0),
                })
    state["sale_ids"] = list(known)
    return new_sales

def check_chats(state):
    # ZeusX не має публічного API для чату — повідомлення недоступні
    return []

def check_token_expiry():
    try:
        token = _access_token()
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        exp = json.loads(base64.b64decode(payload).decode()).get("exp", 0)
        mins_left = int((exp - time.time()) / 60)
        if mins_left < 30:
            print(f"⏰ Токен закінчується через {mins_left} хв — оновлюємо...", flush=True)
            _refresh_token()
        if mins_left <= 0:
            tg_send("⚠️ <b>Токен ZeusX протух!</b>\nОнови ZEUSX_COOKIE в налаштуваннях Railway → Variables")
    except: pass

def main():
    if not ZEUSX_COOKIE:
        print("❌ ZEUSX_COOKIE не встановлено! Додай в Railway Variables", flush=True)
        return
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ TG_TOKEN або TG_CHAT_ID не встановлено!", flush=True)
        return

    print(f"🤖 ZeusX Monitor Bot запущено. Інтервал: {CHECK_INTERVAL}с", flush=True)
    tg_send("🤖 <b>Monitor Bot запущено!</b>\nБуду надсилати сповіщення про продажі та повідомлення ZeusX 24/7 ✅")

    state = load_state()
    iteration = 0

    while True:
        try:
            print(f"[{time.strftime('%H:%M:%S')}] Перевірка #{iteration+1}", flush=True)
            check_token_expiry()

            listings = get_all_listings()
            print(f"  📦 {len(listings)} лотів", flush=True)

            for s in check_sales(listings, state):
                tg_send(f"💰 <b>НОВИЙ ПРОДАЖ!</b>\n🎮 {s['title']}\n👤 <b>{s['buyer']}</b>\n💵 <b>${s['price']:.2f}</b>")


            state["initialized"] = True
            state["iterations"] = state.get("iterations", 0) + 1
            save_state(state)
            iteration += 1
        except Exception as ex:
            print(f"❌ {ex}", flush=True)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
