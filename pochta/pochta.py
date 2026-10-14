#!/usr/bin/env python3
"""Omina Times pochtasi.

O'quvchi yuborgan narsalarni qabul qiladi va muharrirga maxfiy havola orqali
ko'rsatadi:
  POST /pochta/yukla  — muqova surati (image/jpeg)
  POST /pochta/javob  — qisqa matnli javob (application/json: {savol, javob})
  /pochta/oyin/...    — «Rost yoki jasorat» o'yini (mantig'i oyin.py'da)
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
</style></head>
<body><main><div class="varaq">
<h1>Tahririyat pochtasi</h1>
<p class="soni">Javoblar: {{JAVOB_SONI}} · Muqovalar: {{SONI}} · sahifa har 30 soniyada yangilanadi</p>
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


# ── HTTP ────────────────────────────────────────────────────────────────────
class Ishlovchi(BaseHTTPRequestHandler):
    server_version = "OminaPochta"
    sys_version = ""

    def log_message(self, fmt, *args):
        yol = self.path.split("?")[0]
        if yol == "/pochta/oyin/holat":   # har 1.5 soniyada so'raladi — logni to'ldirmasin
            return
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
        if yol.startswith("/pochta/oyin/"):
            return self._oyin_post(yol[len("/pochta/oyin/"):])
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

    def _oyin_post(self, amal):
        if not oyin_ruxsatmi(self._ip()):
            return self._json(429, ok=False, xato="Juda tez. Bir soniya kut.")
        try:
            d = self._json_oqi(OYIN_HAJM)
            if amal == "yangi":
                natija = oyin.yangi(d.get("ism"))
            elif amal == "qoshil":
                natija = oyin.qoshil(d.get("kod"), d.get("ism"))
            elif amal == "harakat":
                natija = {"holat": oyin.harakat(d.get("kod"), d.get("token"), d.get("tur"), d)}
            else:
                return self._json(404, ok=False)
        except oyin.OyinXatosi as e:
            return self._json(e.kod, ok=False, xato=e.matn)
        self._json(200, ok=True, **natija)

    def _oyin_holat(self):
        so_rov = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        try:
            h = oyin.holat(so_rov.get("kod", [""])[0], so_rov.get("token", [""])[0])
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
        if yol == "/pochta/oyin/holat":
            return self._oyin_holat()
        if yol == GALEREYA[:-1]:
            return self._javob(301, qoshimcha={"Location": GALEREYA})
        maxfiy = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}
        if yol == GALEREYA:
            return self._javob(200, galereya(), "text/html; charset=utf-8", maxfiy)
        if yol.startswith(GALEREYA):
            nom = yol[len(GALEREYA):]
            to_liq = os.path.join(PAPKA, nom)
            if NOM_RE.match(nom) and os.path.isfile(to_liq):
                with open(to_liq, "rb") as f:
                    return self._javob(200, f.read(), "image/jpeg", maxfiy)
        self._javob(404, "Topilmadi", "text/plain; charset=utf-8")


if __name__ == "__main__":
    os.makedirs(PAPKA, exist_ok=True)
    print("Omina pochtasi ishga tushdi; telegram:", "yoqilgan" if BOT_TOKEN and CHAT_ID else "o'chiq", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Ishlovchi).serve_forever()
