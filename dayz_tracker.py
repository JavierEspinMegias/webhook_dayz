# dayz_tracker.py
import os, json, requests, hashlib
from datetime import datetime, timezone
import re, json

DAYZ_SERVER_KEY = os.getenv("DAYZ_SERVER_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
PERIOD = os.getenv("PERIOD", datetime.now(timezone.utc).strftime("%Y-%m"))  # YYYY-MM
STATE_FILE = "state.json"

# --------- util estado opcional ---------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

def parse_webhook(url: str):
    """
    https://discord.com/api/webhooks/{id}/{token}
    devuelve (id, token, base_url)
    """
    m = re.search(r"/webhooks/(\d+)/([^/\s?]+)", url)
    if not m:
        return None, None, None
    wid, wtoken = m.group(1), m.group(2)
    base = f"https://discord.com/api/webhooks/{wid}/{wtoken}"
    return wid, wtoken, base

def send_or_edit_discord(content: str, webhook_url: str, state: dict) -> bool:
    wid, wtoken, base = parse_webhook(webhook_url)
    if not wid:
        print("[webhook] URL inválida")
        return False

    # Si ya tenemos message_id, intentamos EDIT (PATCH)
    message_id = state.get("webhook_message_id")
    if message_id:
        patch_url = f"{base}/messages/{message_id}"
        r = requests.patch(patch_url, json={"content": content[:1990] or "(vacío)"}, timeout=15)
        print("[discord] PATCH status:", r.status_code)
        if r.status_code in (200, 204):
            return True
        # si no existe (borrado/limpiado), volvemos a crear
        print("[discord] PATCH falló, re-creando:", r.text[:200])

    # Crear uno nuevo y guardar id (usar ?wait=true para recibir el objeto)
    post_url = f"{base}?wait=true"
    r = requests.post(post_url, json={"content": content[:1990] or "(vacío)"}, timeout=15)
    print("[discord] POST status:", r.status_code)
    if r.status_code == 200:
        msg = r.json()
        state["webhook_message_id"] = str(msg.get("id"))
        save_state(state)
        return True
    elif r.status_code == 204:
        # 204 no devuelve cuerpo => no podemos guardar id; como fallback,
        # seguiremos posteando nuevo cada vez (no ideal). Intenta activar ?wait=true.
        print("[discord] POST 204 (sin id); activa ?wait=true")
        return True
    else:
        print("[discord] POST error:", r.text[:300])
        return False
# --------- helpers extracción ---------
def pick_first_nonempty(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k] is not None:
            s = str(d[k]).strip()
            if s:
                return s
    return None

def extract_user_and_steam(e):
    """
    Devuelve (username, steamid) intentando múltiples alias.
    Acepta dicts o strings.
    """
    if isinstance(e, str):
        s = e.strip()
        return (s if s else "Desconocido", None)

    if not isinstance(e, dict):
        return ("Desconocido", None)

    uname = pick_first_nonempty(e, [
        "username","name","nickname","steamname","steam_name",
        "user","player","voter","display_name","Name","User","nick","title"
    ])

    sid = pick_first_nonempty(e, [
        "steamid","steam_id","steamId","steamID","steamID64","steam",
        "SteamID","steamid64","id"
    ])

    # normaliza algunos formatos
    if sid and sid.lower().startswith("steam:"):
        sid = sid.split(":", 1)[-1].strip() or sid

    return (uname or "Desconocido", sid or None)

# --------- API dayz-servers ---------
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

def api_claim_last24h(username: str):
    """
    Devuelve (voted_last_24h, claimed) usando endpoint 'votes/claim' por username.
    Interpreta '1/0', 'true/false' o JSON.
    """
    url = f"https://dayz-servers.org/api/?object=votes&element=claim&key={DAYZ_SERVER_KEY}&username={requests.utils.quote(username)}"
    try:
        r = requests.get(url, timeout=10)
        try:
            data = r.json()
            val = str(data).lower()
        except ValueError:
            val = r.text.strip().lower()
        voted = any(x in val for x in ("1","true","yes"))
        claimed = ("claimed" in val and "true" in val)
        return voted, claimed
    except Exception as e:
        print(f"[api24h] error username={username} ->", e)
        return None, None

# --------- Discord webhook ---------
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

# --------- main ---------
def main():
    print("HAS DAYZ_SERVER_KEY:", bool(DAYZ_SERVER_KEY))
    print("HAS DISCORD_WEBHOOK:", bool(DISCORD_WEBHOOK))
    print("PERIOD:", PERIOD)

    if not DAYZ_SERVER_KEY or not DISCORD_WEBHOOK:
        print("⛔ Faltan DAYZ_SERVER_KEY o DISCORD_WEBHOOK")
        return

    st = load_state()
    seen = set(st.get("seen", []))

    # 1) Traer datos
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
    # Muestra ejemplo de estructura (primeros 5)
    print("[debug] type(voters):", type(voters).__name__, "len:", len(voters))
    for i, e in enumerate(voters[:5], start=1):
        print(f"[debug] sample #{i}:", type(e).__name__)
        if isinstance(e, dict):
            keys = list(e.keys())
            print("   keys:", keys)
            print("   raw:", {k: e[k] for k in keys[:8]})
        else:
            print("   raw:", e)

    # 2) Construir líneas (TODOS los votantes), marcando 24h si se puede
    lines = []
    for i, e in enumerate(voters, start=1):
        uname, sid = extract_user_and_steam(e)

        voted24 = claimed = None
        if uname and uname != "Desconocido":
            voted24, claimed = api_claim_last24h(uname)

        v24_tag = "✅24h" if voted24 else ("❌24h" if voted24 is False else "??24h")
        clm_tag = "🧾" if claimed else ("no-claimed" if claimed is False else "claimed?")

        lines.append(f"{i:03d}. {uname}{f' ({sid})' if sid else ''} [{v24_tag} | {clm_tag}]")

    # 3) Mensaje y envío
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"🛰️ DayZ voters • {PERIOD} • {today}"
    body = "\n".join(lines) if lines else "(sin datos)"
    text = f"{header}\n\n{body}"

    # límite de Discord
    if len(text) > 1900:
        text = text[:1900] + "\n…"

    try:
        ok = send_or_edit_discord(text, DISCORD_WEBHOOK, st)
        print("[main] enviado a Discord:", ok)
    except Exception as e:
        print("[main] error enviando a Discord:", e)
        raise

    # 4) Persistir estado (por si luego lo usas)
    st["seen"] = sorted(list(seen))
    save_state(st)
    print("[main] fin ok")

if __name__ == "__main__":
    main()
