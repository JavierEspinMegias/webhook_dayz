import os, json, time, hashlib, requests
from datetime import datetime, timezone

DAYZ_SERVER_KEY = os.getenv("DAYZ_SERVER_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
PERIOD = os.getenv("PERIOD", datetime.now(timezone.utc).strftime("%Y-%m"))
STATE_FILE = "state.json"

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[state] nuevo o ilegible:", e)
        return {"seen": []}

def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

def api_voters():
    url = f"https://dayz-servers.org/api/?object=servers&element=voters&key={DAYZ_SERVER_KEY}&month={PERIOD}&format=json"
    print("[api] GET", url)
    r = requests.get(url, timeout=15)
    print("[api] status", r.status_code)
    ct = r.headers.get("content-type", "")
    print("[api] content-type", ct)
    preview = r.text[:200].replace("\n"," ")
    print("[api] preview", preview)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError as e:
        print("[api] JSON error:", e)
        return {}

def send_discord(text: str):
    if not DISCORD_WEBHOOK:
        print("[discord] faltan secrets")
        return False
    payload = {"content": (text[:1990] or "(mensaje vacío)")}

    print("[discord] POST", DISCORD_WEBHOOK[:60] + "…")
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
    print("[discord] status:", r.status_code, r.reason)
    if r.status_code not in (200, 204):
        print("[discord] body:", r.text[:500])
    r.raise_for_status()
    return True

def main():
    print("HAS DAYZ_SERVER_KEY:", bool(DAYZ_SERVER_KEY))
    print("HAS DISCORD_WEBHOOK:", bool(DISCORD_WEBHOOK))
    print("PERIOD:", PERIOD)

    st = load_state()
    seen = set(st.get("seen", []))

    try:
        data = api_voters()
    except Exception as e:
        print("[main] error consultando API:", e)
        data = {}

    voters = []
    if isinstance(data, dict):
        voters = data.get("voters") or data.get("data") or []
    elif isinstance(data, list):
        voters = data
    print("[main] voters len:", len(voters))

    # Mensaje simple para verificar envío aunque no haya datos
    lines = []
    for i, e in enumerate(voters, start=1):
        uname = (e.get("username") or e.get("name") or "").strip() or "Desconocido"
        sid = str(e.get("steamid") or e.get("steam_id") or "").strip()
        lines.append(f"{i:03d}. {uname}{f' ({sid})' if sid else ''}")

    body = "\n".join(lines) if lines else "(sin datos)"
    text = f"🛰️ DayZ voters ({len(lines)}):\n{body}"

    try:
        ok = send_discord(text)
        print("[main] enviado a Discord:", ok)
    except Exception as e:
        print("[main] error enviando a Discord:", e)
        raise

    st["seen"] = sorted(list(seen))
    save_state(st)
    print("[main] fin ok")

if __name__ == "__main__":
    main()
