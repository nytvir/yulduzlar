#!/usr/bin/env python3
"""Omina Times pochtasi.

O'quvchi yuborgan narsalarni qabul qiladi va muharrirga maxfiy havola orqali
ko'rsatadi:
  POST /pochta/yukla  — muqova surati (image/jpeg)
  POST /pochta/javob  — qisqa matnli javob (application/json: {savol, javob})
  /pochta/oyin/...    — «Rost yoki jasorat» o'yini (mantig'i oyin.py'da)
  /pochta/tele/...    — «Telepatiya» o'yini (mantig'i telepatiya.py'da)
BOT_TOKEN va CHAT_ID berilsa, har biri Telegram'ga ham yuboriladi.

Muhit o'zgaruvchilari:
  POCHTA_KALIT  — galereya havolasidagi maxfiy qism (majburiy)
  POCHTA_PAPKA  — ma'lumotlar papkasi (standart: /data)
  BOT_TOKEN     — Telegram bot tokeni (ixtiyoriy)
  CHAT_ID       — Telegram chat (ixtiyoriy)
"""
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import oyin
import telepatiya

OYINLAR = {"oyin": oyin, "tele": telepatiya}     # /pochta/<nom>/... → o'yin moduli

PAPKA = os.environ.get("POCHTA_PAPKA", "/data")
KALIT = os.environ["POCHTA_KALIT"].strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

MAX_HAJM = 6 * 1024 * 1024          # bitta muqova uchun yuqori chegara
MAX_FAYL = 300                      # disk to'lib qolmasligi uchun
MAX_JAVOB_HAJM = 8192               # bitta javob so'rovi, bayt
MAX_JAVOB_UZUNLIK = 600             # savol va javob matni, belgi (test natijasi bir necha qator)
MAX_JAVOB_SONI = 500
LIMIT_SONI, LIMIT_DAVR = 6, 600     # bitta IP'dan 10 daqiqada 6 ta
TOSHKENT = timezone(timedelta(hours=5))
NOM_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}\.jpg$")
GALEREYA = f"/pochta/{KALIT}/"
JAVOBLAR = os.path.join(PAPKA, "javoblar.jsonl")
OYIN_ARXIV = os.path.join(PAPKA, "oyin_tarixi.jsonl")
MAX_ARXIV = 5000                    # o'yin arxividagi yozuvlar soni chegarasi

if not re.fullmatch(r"[0-9a-f]{16,64}", KALIT):
    raise SystemExit("POCHTA_KALIT 16–64 belgili hex bo'lishi kerak")

OYIN_LIMIT, OYIN_DAVR = 120, 60     # o'yin harakatlari: bitta IP'dan daqiqada 120 ta
OYIN_HAJM = 4096

_urinishlar = defaultdict(deque)
_oyin_urinishlar = defaultdict(deque)
_qulf = threading.Lock()
_javob_qulfi = threading.Lock()


def ruxsatmi(ip):
    hozir = time.monotonic()
    with _qulf:
        q = _urinishlar[ip]
        while q and hozir - q[0] > LIMIT_DAVR:
            q.popleft()
        if len(q) >= LIMIT_SONI:
            return False
        q.append(hozir)
        return True


def oyin_ruxsatmi(ip):
    hozir = time.monotonic()
    with _qulf:
        q = _oyin_urinishlar[ip]
        while q and hozir - q[0] > OYIN_DAVR:
            q.popleft()
        if len(q) >= OYIN_LIMIT:
            return False
        q.append(hozir)
        return True


def fayllar():
    return sorted((f for f in os.listdir(PAPKA) if NOM_RE.match(f)), reverse=True)


def javoblar():
    try:
        with open(JAVOBLAR, encoding="utf-8") as f:
            qatorlar = f.readlines()
    except FileNotFoundError:
        return []
    natija = []
    for q in reversed(qatorlar):
        try:
            natija.append(json.loads(q))
        except ValueError:
            continue
    return natija


# ── o'yin arxivi ────────────────────────────────────────────────────────────
_arxiv_qulfi = threading.Lock()


def arxivga(yozuv):
    """oyin.py tarixga yozgan har bir kartani diskka ham saqlaydi."""
    with _arxiv_qulfi:
        try:
            with open(OYIN_ARXIV, encoding="utf-8") as f:
                soni = sum(1 for _ in f)
        except FileNotFoundError:
            soni = 0
        if soni >= MAX_ARXIV:
            return
        with open(OYIN_ARXIV, "a", encoding="utf-8") as f:
            f.write(json.dumps(yozuv, ensure_ascii=False) + "\n")


oyin.ARXIVGA = arxivga
telepatiya.ARXIVGA = arxivga


def arxiv_oqi():
    try:
        with open(OYIN_ARXIV, encoding="utf-8") as f:
            qatorlar = f.readlines()
    except FileNotFoundError:
        return []
    natija = []
    for q in qatorlar:
        try:
            natija.append(json.loads(q))
        except ValueError:
            continue
    return natija


def hozir_matn():
    return datetime.now(TOSHKENT).strftime("%d.%m.%Y, %H:%M")


# ── Telegram (ixtiyoriy) ─────────────────────────────────────────────────────
def _telegram(usul, tana, sarlavhalar):
    try:
        so_rov = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{usul}", data=tana, headers=sarlavhalar
        )
        urllib.request.urlopen(so_rov, timeout=30).read()
    except Exception as e:  # token logga tushmasligi uchun faqat xato turi yoziladi
        print("telegram xatosi:", type(e).__name__, flush=True)


def telegramga_rasm(yol, nom):
    if not (BOT_TOKEN and CHAT_ID):
        return
    chegara = "----omina" + secrets.token_hex(8)
    with open(yol, "rb") as f:
        rasm = f.read()
    qismlar = []
    for n, v in (("chat_id", CHAT_ID), ("caption", "📰 Omina Times — yangi muqova keldi")):
        qismlar.append(f'--{chegara}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode())
    qismlar.append(
        f'--{chegara}\r\nContent-Disposition: form-data; name="photo"; filename="{nom}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n".encode() + rasm + b"\r\n"
    )
    qismlar.append(f"--{chegara}--\r\n".encode())
    _telegram("sendPhoto", b"".join(qismlar), {"Content-Type": f"multipart/form-data; boundary={chegara}"})


def telegramga_matn(matn):
    if not (BOT_TOKEN and CHAT_ID):
        return
    tana = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": matn}).encode()
    _telegram("sendMessage", tana, {"Content-Type": "application/x-www-form-urlencoded"})


# ── Galereya ────────────────────────────────────────────────────────────────
def vaqt(nom):
    return datetime.strptime(nom[:15], "%Y%m%d-%H%M%S").strftime("%d.%m.%Y, %H:%M")


SHABLON = """<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="refresh" content="30">
<title>Tahririyat pochtasi</title>
<style>
  :root{--qogoz:#F2ECDF;--siyoh:#1C1915;--siyoh-2:#4A443A;--qizil:#A8261C;--stol:#2B2722}
  *{box-sizing:border-box}
  body{margin:0;background:var(--stol);color:var(--siyoh);font-family:Georgia,"Times New Roman",serif}
  main{max-width:960px;margin:0 auto;padding:24px 16px 48px}
  .varaq{background:var(--qogoz);padding:20px 16px 28px}
  h1{margin:0;font-size:30px;text-align:center}
  h2{margin:26px 0 12px;padding:6px 0;border-top:3px solid var(--siyoh);border-bottom:1px solid var(--siyoh);
     font-family:"Arial Narrow",sans-serif;font-size:13px;letter-spacing:.18em;text-transform:uppercase}
  .soni{margin:6px 0 0;text-align:center;font-family:"Arial Narrow",sans-serif;font-size:12px;
        letter-spacing:.14em;text-transform:uppercase;color:var(--siyoh-2);border-block:1px solid var(--siyoh);padding:6px 0}
  .javoblar{list-style:none;margin:0;padding:0;display:grid;gap:8px}
  .javoblar li{border:1px solid var(--siyoh);padding:10px 12px;display:grid;gap:2px}
  .javoblar b{font-size:18px;line-height:1.5;white-space:pre-line}
  .javoblar span,.javoblar time{font-size:14px;font-style:italic;color:var(--siyoh-2)}
  .tor{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
  figure{margin:0}
  img{width:100%;height:auto;display:block;border:1px solid rgba(28,25,21,.25)}
  figcaption{margin-top:6px;font-style:italic;font-size:14px;color:var(--siyoh-2)}
  .bosh{font-style:italic;color:var(--siyoh-2);margin:0}
  a:focus-visible{outline:3px solid var(--qizil);outline-offset:3px}
  .havola{margin:12px 0 0;text-align:center}
  .havola a{display:inline-block;padding:10px 16px;background:var(--siyoh);color:var(--qogoz);text-decoration:none;
            font-family:"Arial Narrow",sans-serif;font-weight:700;font-size:13px;letter-spacing:.12em;text-transform:uppercase}
</style></head>
<body><main><div class="varaq">
<h1>Tahririyat pochtasi</h1>
<p class="soni">Javoblar: {{JAVOB_SONI}} · Muqovalar: {{SONI}} · sahifa har 30 soniyada yangilanadi</p>
<p class="havola"><a href="oyin">O'yinlar arxivi →</a></p>
<h2>Javoblar</h2>
{{JAVOBLAR}}
<h2>Muqovalar</h2>
<div class="tor">{{KARTALAR}}</div>
</div></main></body></html>"""


def galereya():
    royxat = fayllar()
    kartalar = "".join(
        f'<figure><a href="{html.escape(n)}"><img src="{html.escape(n)}" loading="lazy" alt="Muqova"></a>'
        f"<figcaption>{vaqt(n)}</figcaption></figure>"
        for n in royxat
    ) or "<p class=\"bosh\">Hozircha muqova kelmadi.</p>"
    jv = javoblar()
    javob_html = (
        '<ul class="javoblar">'
        + "".join(
            f"<li><b>{html.escape(str(j.get('javob', '')))}</b>"
            f"<span>{html.escape(str(j.get('savol', '')))}</span>"
            f"<time>{html.escape(str(j.get('vaqt', '')))}</time></li>"
            for j in jv
        )
        + "</ul>"
    ) if jv else "<p class=\"bosh\">Hozircha javob kelmadi.</p>"
    return (SHABLON
            .replace("{{SONI}}", str(len(royxat)))
            .replace("{{JAVOB_SONI}}", str(len(jv)))
            .replace("{{JAVOBLAR}}", javob_html)
            .replace("{{KARTALAR}}", kartalar))


ARXIV_SHABLON = """<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="refresh" content="30">
<title>O'yinlar arxivi</title>
<style>
  :root{--qogoz:#F2ECDF;--siyoh:#1C1915;--siyoh-2:#4A443A;--qizil:#A8261C;--kok:#2F4A7A;--stol:#2B2722}
  *{box-sizing:border-box}
  body{margin:0;background:var(--stol);color:var(--siyoh);font-family:Georgia,"Times New Roman",serif}
  main{max-width:760px;margin:0 auto;padding:24px 12px 48px}
  .varaq{background:var(--qogoz);padding:20px 16px 28px}
  h1{margin:0;font-size:30px;text-align:center}
  .orqa{display:block;margin:0 0 12px;font-family:"Arial Narrow",sans-serif;font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--siyoh-2)}
  .soni{margin:6px 0 0;text-align:center;font-family:"Arial Narrow",sans-serif;font-size:12px;letter-spacing:.14em;
        text-transform:uppercase;color:var(--siyoh-2);border-block:1px solid var(--siyoh);padding:6px 0}
  .oyin{margin-top:22px}
  .oyin h2{margin:0;padding:7px 0;border-top:3px solid var(--siyoh);border-bottom:1px solid var(--siyoh);
           display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;
           font-family:"Arial Narrow",sans-serif;font-size:13px;letter-spacing:.14em;text-transform:uppercase}
  .oyin h2 span:last-child{color:var(--siyoh-2)}
  ol{list-style:none;margin:0;padding:0}
  li{padding:12px 0;border-bottom:1px solid rgba(28,25,21,.2);display:grid;gap:4px}
  .bosh{display:flex;justify-content:space-between;gap:10px;font-family:"Arial Narrow",sans-serif;font-weight:700;font-size:12.5px;letter-spacing:.1em;text-transform:uppercase}
  .rost{color:var(--kok)} .jasorat{color:var(--qizil)} .telepatiya{color:#6B3FA0}
  .savol{font-style:italic;color:var(--siyoh-2);font-size:15px}
  .javob{font-size:18px;line-height:1.45;word-break:break-word}
  .yoq{font-style:italic;color:var(--siyoh-2)}
  .bosh-holat{font-style:italic;color:var(--siyoh-2);text-align:center;margin:24px 0 0}
  a:focus-visible{outline:3px solid var(--qizil);outline-offset:3px}
</style></head>
<body><main><div class="varaq">
<a class="orqa" href="./">← Tahririyat pochtasi</a>
<h1>O'yinlar arxivi</h1>
<p class="soni">O'yinlar: {{OYIN_SONI}} · Kartalar: {{KARTA_SONI}} · sahifa har 30 soniyada yangilanadi</p>
{{OYINLAR}}
</div></main></body></html>"""


TUR_NOMI = {"rost": "Rost", "jasorat": "Jasorat", "telepatiya": "Telepatiya"}
QISM_NOMI = {"odatiy": "Rost yoki jasorat 1", "ikkinchi": "Rost yoki jasorat 2",
             "shaxsiy": "O'z savollarimiz", "telepatiya": "Telepatiya"}


def oyin_arxivi():
    yozuvlar = arxiv_oqi()
    guruhlar = {}
    for y in yozuvlar:
        guruhlar.setdefault(str(y.get("xona", "?")), []).append(y)
    # eng so'nggi o'ynalgan xona birinchi
    tartib = sorted(guruhlar.items(), key=lambda g: max(float(y.get("vaqt", 0)) for y in g[1]), reverse=True)

    def vaqt_matn(t):
        try:
            return datetime.fromtimestamp(float(t), TOSHKENT).strftime("%d.%m.%Y, %H:%M")
        except (TypeError, ValueError):
            return ""

    bloklar = []
    for kod, royxat in tartib:
        oyinchilar = " va ".join(html.escape(str(i)) for i in (royxat[0].get("oyinchilar") or []) if i)
        qism = QISM_NOMI.get(royxat[0].get("rejim") or ("telepatiya" if royxat[0].get("tur") == "telepatiya" else "odatiy"), "")
        boshlandi = vaqt_matn(min(float(y.get("vaqt", 0)) for y in royxat))
        satrlar = []
        for y in reversed(royxat):        # o'yin ichida eng yangisi tepada
            tur = y.get("tur") if y.get("tur") in TUR_NOMI else "jasorat"
            muallif = f'<b>{html.escape(str(y["muallif"]))} so\'radi:</b> ' if y.get("muallif") else ""
            if y.get("natija") == "qabul":
                ochko = f"+{int(y.get('ochko', 0))} ✓"
            elif tur == "telepatiya":
                ochko = "topilmadi"
            else:
                ochko = "o'tkazdi" + (f" ({int(y.get('ochko', 0))})" if y.get("ochko") else "")
            if y.get("javob"):
                javob = f'<div class="javob">«{html.escape(str(y["javob"]))}»</div>'
            elif y.get("natija") == "qabul":
                javob = '<div class="javob yoq">Bajarildi ✓</div>'
            else:
                javob = '<div class="javob yoq">Javob berilmadi</div>'
            satrlar.append(
                f'<li><div class="bosh"><span>{html.escape(str(y.get("kim", "")))} · '
                f'<span class="{tur}">{TUR_NOMI[tur]}</span></span>'
                f'<span>{ochko} · {vaqt_matn(y.get("vaqt"))[-5:]}</span></div>'
                f'<div class="savol">{muallif}{html.escape(str(y.get("savol", "")))}</div>{javob}</li>'
            )
        bloklar.append(
            f'<section class="oyin"><h2><span>{qism} · Xona {html.escape(kod)} · {oyinchilar}</span>'
            f"<span>{boshlandi}</span></h2><ol>{''.join(satrlar)}</ol></section>"
        )
    return (ARXIV_SHABLON
            .replace("{{OYIN_SONI}}", str(len(guruhlar)))
            .replace("{{KARTA_SONI}}", str(len(yozuvlar)))
            .replace("{{OYINLAR}}", "".join(bloklar) or '<p class="bosh-holat">Hozircha o\'yin bo\'lmadi.</p>'))


# ── HTTP ────────────────────────────────────────────────────────────────────
class Ishlovchi(BaseHTTPRequestHandler):
    server_version = "OminaPochta"
    sys_version = ""

    def log_message(self, fmt, *args):
        yol = self.path.split("?")[0]
        if yol.endswith("/holat") and yol.split("/")[2:3] and yol.split("/")[2] in OYINLAR:
            return                        # har 1.5 soniyada so'raladi — logni to'ldirmasin
        if yol.startswith(GALEREYA):
            yol = "/pochta/[galereya]/"
        print(f"{self.command} {yol[:60]}", flush=True)

    def _ip(self):
        xf = self.headers.get("X-Forwarded-For", "")
        return xf.split(",")[0].strip() or self.client_address[0]

    def _javob(self, http_kod, tana=b"", tur="application/json; charset=utf-8", qoshimcha=None):
        if isinstance(tana, str):
            tana = tana.encode()
        self.send_response(http_kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(tana)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (qoshimcha or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(tana)

    def _json(self, http_kod, **d):
        self._javob(http_kod, json.dumps(d, ensure_ascii=False))

    def _turi(self):
        return self.headers.get("Content-Type", "").split(";")[0].strip().lower()

    def _hajm(self):
        try:
            return int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return 0

    def do_POST(self):
        yol = self.path.split("?")[0]
        if yol == "/pochta/yukla":
            return self._muqova_qabul()
        if yol == "/pochta/javob":
            return self._javob_qabul()
        qismlar = yol.split("/")                       # ["", "pochta", "<o'yin>", "<amal>"]
        if len(qismlar) == 4 and qismlar[2] in OYINLAR:
            return self._oyin_post(OYINLAR[qismlar[2]], qismlar[3])
        self._json(404, ok=False)

    # ── o'yin ──────────────────────────────────────────────────────────────
    def _json_oqi(self, chegara):
        if self._turi() != "application/json":
            raise oyin.OyinXatosi(415, "faqat json")
        hajm = self._hajm()
        if hajm <= 0 or hajm > chegara:
            raise oyin.OyinXatosi(413, "hajm")
        try:
            d = json.loads(self.rfile.read(hajm).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise oyin.OyinXatosi(400, "json emas")
        if not isinstance(d, dict):
            raise oyin.OyinXatosi(400, "json emas")
        return d

    def _oyin_post(self, modul, amal):
        if not oyin_ruxsatmi(self._ip()):
            return self._json(429, ok=False, xato="Juda tez. Bir soniya kut.")
        try:
            d = self._json_oqi(OYIN_HAJM)
            if amal == "yangi":
                natija = modul.yangi(d)
            elif amal == "qoshil":
                natija = modul.qoshil(d.get("kod"), d.get("ism"))
            elif amal == "harakat":
                natija = {"holat": modul.harakat(d.get("kod"), d.get("token"), d.get("tur"), d)}
            else:
                return self._json(404, ok=False)
        except oyin.OyinXatosi as e:
            return self._json(e.kod, ok=False, xato=e.matn)
        self._json(200, ok=True, **natija)

    def _oyin_holat(self, modul):
        so_rov = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        try:
            h = modul.holat(so_rov.get("kod", [""])[0], so_rov.get("token", [""])[0])
        except oyin.OyinXatosi as e:
            return self._json(e.kod, ok=False, xato=e.matn)
        self._json(200, ok=True, holat=h)

    def _muqova_qabul(self):
        if self._turi() != "image/jpeg":
            return self._json(415, ok=False, xato="faqat jpeg")
        hajm = self._hajm()
        if hajm <= 0 or hajm > MAX_HAJM:
            return self._json(413, ok=False, xato="hajm")
        if not ruxsatmi(self._ip()):
            return self._json(429, ok=False, xato="ko'p urinish")
        tana = self.rfile.read(hajm)
        if len(tana) != hajm or not tana.startswith(b"\xff\xd8\xff"):
            return self._json(400, ok=False, xato="rasm emas")
        if len(fayllar()) >= MAX_FAYL:
            return self._json(507, ok=False, xato="joy tugadi")

        nom = datetime.now(TOSHKENT).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4) + ".jpg"
        yol = os.path.join(PAPKA, nom)
        with open(yol + ".tmp", "wb") as f:
            f.write(tana)
        os.replace(yol + ".tmp", yol)
        threading.Thread(target=telegramga_rasm, args=(yol, nom), daemon=True).start()
        self._json(200, ok=True)

    def _javob_qabul(self):
        if self._turi() != "application/json":
            return self._json(415, ok=False, xato="faqat json")
        hajm = self._hajm()
        if hajm <= 0 or hajm > MAX_JAVOB_HAJM:
            return self._json(413, ok=False, xato="hajm")
        if not ruxsatmi(self._ip()):
            return self._json(429, ok=False, xato="ko'p urinish")
        try:
            d = json.loads(self.rfile.read(hajm).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(400, ok=False, xato="json emas")
        if not isinstance(d, dict):
            return self._json(400, ok=False, xato="json emas")
        savol = str(d.get("savol", "")).strip()[:MAX_JAVOB_UZUNLIK]
        javob = str(d.get("javob", "")).strip()[:MAX_JAVOB_UZUNLIK]
        if not javob:
            return self._json(400, ok=False, xato="javob bo'sh")

        yozuv = {"vaqt": hozir_matn(), "savol": savol, "javob": javob}
        with _javob_qulfi:
            if len(javoblar()) >= MAX_JAVOB_SONI:
                return self._json(507, ok=False, xato="joy tugadi")
            with open(JAVOBLAR, "a", encoding="utf-8") as f:
                f.write(json.dumps(yozuv, ensure_ascii=False) + "\n")
        threading.Thread(
            target=telegramga_matn, args=(f"💌 Omina'dan javob: {javob}\n({savol})",), daemon=True
        ).start()
        self._json(200, ok=True)

    def do_GET(self):
        yol = self.path.split("?")[0]
        if yol == "/pochta/salomat":
            return self._json(200, ok=True)
        q = yol.split("/")
        if len(q) == 4 and q[2] in OYINLAR and q[3] == "holat":
            return self._oyin_holat(OYINLAR[q[2]])
        if yol == GALEREYA[:-1]:
            return self._javob(301, qoshimcha={"Location": GALEREYA})
        maxfiy = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
        if yol == GALEREYA:
            return self._javob(200, galereya(), "text/html; charset=utf-8", maxfiy)
        if yol in (GALEREYA + "oyin", GALEREYA + "oyin/"):
            return self._javob(200, oyin_arxivi(), "text/html; charset=utf-8", maxfiy)
        if yol.startswith(GALEREYA):
            nom = yol[len(GALEREYA):]
            to_liq = os.path.join(PAPKA, nom)
            if NOM_RE.match(nom) and os.path.isfile(to_liq):
                with open(to_liq, "rb") as f:
                    return self._javob(200, f.read(), "image/jpeg", maxfiy)
        self._javob(404, "Topilmadi", "text/plain; charset=utf-8")


XONALAR_FAYLI = os.path.join(PAPKA, "xonalar.json")


def xonalarni_saqla():
    malumot = {nom: modul.eksport() for nom, modul in OYINLAR.items()}
    with open(XONALAR_FAYLI + ".tmp", "w", encoding="utf-8") as f:
        json.dump(malumot, f, ensure_ascii=False)
    os.replace(XONALAR_FAYLI + ".tmp", XONALAR_FAYLI)
    return sum(len(v) for v in malumot.values())


def xonalarni_tikla():
    try:
        with open(XONALAR_FAYLI, encoding="utf-8") as f:
            malumot = json.load(f)
    except (FileNotFoundError, ValueError):
        return 0
    for nom, modul in OYINLAR.items():
        modul.import_(malumot.get(nom))
    os.remove(XONALAR_FAYLI)
    return sum(len(v) for v in malumot.values())


if __name__ == "__main__":
    import signal
    import sys

    os.makedirs(PAPKA, exist_ok=True)
    print("tiklangan xonalar:", xonalarni_tikla(), flush=True)

    def toxta(*_):
        # docker restart/stop SIGTERM yuboradi — ochiq o'yinlar diskka yoziladi
        print("saqlangan xonalar:", xonalarni_saqla(), flush=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, toxta)
    print("Omina pochtasi ishga tushdi; telegram:", "yoqilgan" if BOT_TOKEN and CHAT_ID else "o'chiq", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Ishlovchi).serve_forever()
