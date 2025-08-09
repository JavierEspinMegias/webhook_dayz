import os, json, time, hashlib, requests
from datetime import datetime, timezone

DAYZ_SERVER_KEY = os.getenv("DAYZ_SERVER_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
SERVER_ID = os.getenv("SERVER_ID", "")  # opcional, si quieres trackear un server concreto
PERIOD = os.getenv("PERIOD", datetime.now(timezone.utc).strftime("%Y-%m"))  # YYYY-MM
STATE_FILE = "state.json"

def h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen": []}

def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

def api_voters():
    url = f"https://dayz-servers.org/api/?object=servers&element=voters&key={DAYZ_SERVER_KEY}&month={PERIOD}&format=json"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def api_claim_last24h(username: str):
    url = f"https://dayz-servers.org/api/?object=votes&element=claim&key={DAYZ_SERVER_KEY}&username={requests.utils.quote(username)}"
    try:
        r = requests.get(url, timeout=10)
        try:
            data = r.json()
            val = str(data).lower()
        except ValueError:
            val = r.text.strip().lower()
        voted = any(x in val for x in ("1", "true", "yes"))
        claimed = ("claimed" in val and "true" in val) or ("🧾" in val)
        return voted, None if claimed is False else claimed
    except Exception:
        return None, None

def send_discord(text: str):
    if not DISCORD_WEBHOOK:
        print("No DISCORD_WEBHOOK set")
        return
    payload = {"content": text}
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
    r.raise_for_status()

def main():
    if not DAYZ_SERVER_KEY or not DISCORD_WEBHOOK:
        print("Faltan DAYZ_SERVER_KEY o DISCORD_WEBHOOK")
        return

    st = load_state()
    seen = set(st.get("seen", []))

    data = api_voters()
    voters = data.get("voters") or data.get("data") or []
    lines = []
    new_lines = []

    for i, e in enumerate(voters, start=1):
        uname = (e.get("username") or e.get("name") or "").strip() or "Desconocido"
        sid = str(e.get("steamid") or e.get("steam_id") or "").strip()
        when = e.get("date") or e.get("timestamp") or e.get("time") or ""

        key = f"steam:{sid}" if sid else f"user:{uname.lower()}"
        voted24, claimed = (None, None)
        if uname != "Desconocido":
            voted24, claimed = api_claim_last24h(uname)

        v24 = "✅24h" if voted24 else ("❌24h" if voted24 is False else "??24h")
        clm = "🧾" if claimed else ("no-claimed" if claimed is False else "claimed?")

        is_new = (key not in seen) and (voted24 is True)
        line = f"{'🆕 ' if is_new else ''}{i:03d}. {uname}{f' ({sid})' if sid else ''}{f' • {when}' if when else ''} [{v24} | {clm}]"
        lines.append(line)
        if is_new:
            new_lines.append(line)
            seen.add(key)

    # resumen diario simple (usuarios con ✅24h únicos)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    unique_today = { (e.get('steamid') or (e.get('username') or e.get('name') or '').lower())
                     for e in voters if (e.get('username') or e.get('name')) }
    header = f"📊 **Votantes {PERIOD}**  •  {today}"
    body = "\n".join(lines) if lines else "(sin datos)"
    footer = f"\n\n🆕 nuevos (24h): {len(new_lines)}"
    text = f"{header}\n\n{body}{footer}"
    # Discord limita ~2000 chars
    if len(text) > 1900:
        text 
