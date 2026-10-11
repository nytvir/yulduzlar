#!/usr/bin/env python3
"""Omina Times pochtasi.

Gazetaning 2-sonida o'quvchi tanlagan suratdan yasalgan muqovani qabul qiladi,
diskka saqlaydi va muharrirga maxfiy havola orqali ko'rsatadi. BOT_TOKEN va
CHAT_ID berilsa, muqovani Telegram'ga ham yuboradi.

Muhit o'zgaruvchilari:
  POCHTA_KALIT  — galereya havolasidagi maxfiy qism (majburiy)
  POCHTA_PAPKA  — muqovalar saqlanadigan papka (standart: /data)
  BOT_TOKEN     — Telegram bot tokeni (ixtiyoriy)
  CHAT_ID       — muqova yuboriladigan Telegram chat (ixtiyoriy)
"""
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAPKA = os.environ.get("POCHTA_PAPKA", "/data")
KALIT = os.environ["POCHTA_KALIT"].strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

MAX_HAJM = 6 * 1024 * 1024          # bitta muqova uchun yuqori chegara
MAX_FAYL = 300                      # disk to'lib qolmasligi uchun
LIMIT_SONI, LIMIT_DAVR = 6, 600     # bitta IP'dan 10 daqiqada 6 ta
TOSHKENT = timezone(timedelta(hours=5))
NOM_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}\.jpg$")
GALEREYA = f"/pochta/{KALIT}/"

if not re.fullmatch(r"[0-9a-f]{16,64}", KALIT):
    raise SystemExit("POCHTA_KALIT 16–64 belgili hex bo'lishi kerak")

_urinishlar = defaultdict(deque)
_qulf = threading.Lock()


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


def fayllar():
    return sorted((f for f in os.listdir(PAPKA) if NOM_RE.match(f)), reverse=True)


def telegramga(yol, nom):
    if not (BOT_TOKEN and CHAT_ID):
        return
    try:
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
        so_rov = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data=b"".join(qismlar),
            headers={"Content-Type": f"multipart/form-data; boundary={chegara}"},
        )
        urllib.request.urlopen(so_rov, timeout=30).read()
    except Exception as e:  # token logga tushmasligi uchun faqat xato turi yoziladi
        print("telegram xatosi:", type(e).__name__, flush=True)


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
  .soni{margin:6px 0 18px;text-align:center;font-family:"Arial Narrow",sans-serif;font-size:12px;
        letter-spacing:.14em;text-transform:uppercase;color:var(--siyoh-2);border-block:1px solid var(--siyoh);padding:6px 0}
  .tor{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
  figure{margin:0}
  img{width:100%;height:auto;display:block;border:1px solid rgba(28,25,21,.25)}
  figcaption{margin-top:6px;font-style:italic;font-size:14px;color:var(--siyoh-2)}
  .bosh{text-align:center;font-style:italic;color:var(--siyoh-2)}
  a:focus-visible{outline:3px solid var(--qizil);outline-offset:3px}
</style></head>
<body><main><div class="varaq">
<h1>Tahririyat pochtasi</h1>
<p class="soni">Kelgan muqovalar: {{SONI}} · sahifa har 30 soniyada yangilanadi</p>
<div class="tor">{{KARTALAR}}</div>
</div></main></body></html>"""


def galereya():
    royxat = fayllar()
    kartalar = "".join(
        f'<figure><a href="{html.escape(n)}"><img src="{html.escape(n)}" loading="lazy" alt="Muqova"></a>'
        f"<figcaption>{vaqt(n)}</figcaption></figure>"
        for n in royxat
    ) or "<p class=\"bosh\">Hozircha muqova kelmadi. U suratini tanlaganda shu yerda paydo bo'ladi.</p>"
    return SHABLON.replace("{{SONI}}", str(len(royxat))).replace("{{KARTALAR}}", kartalar)


class Ishlovchi(BaseHTTPRequestHandler):
    server_version = "OminaPochta"
    sys_version = ""

    def log_message(self, fmt, *args):
        yol = self.path.split("?")[0]
        if yol.startswith(GALEREYA):
            yol = "/pochta/[galereya]/"
        print(f"{self.command} {yol[:60]}", flush=True)

    def _ip(self):
        xf = self.headers.get("X-Forwarded-For", "")
        return xf.split(",")[0].strip() or self.client_address[0]

    def _javob(self, kod, tana=b"", tur="application/json; charset=utf-8", qoshimcha=None):
        if isinstance(tana, str):
            tana = tana.encode()
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(tana)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (qoshimcha or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(tana)

    def _json(self, kod, **d):
        self._javob(kod, json.dumps(d, ensure_ascii=False))

    def do_POST(self):
        if self.path.split("?")[0] != "/pochta/yukla":
            return self._json(404, ok=False)
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "image/jpeg":
            return self._json(415, ok=False, xato="faqat jpeg")
        try:
            hajm = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            hajm = 0
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
        threading.Thread(target=telegramga, args=(yol, nom), daemon=True).start()
        self._json(200, ok=True)

    def do_GET(self):
        yol = self.path.split("?")[0]
        if yol == "/pochta/salomat":
            return self._json(200, ok=True)
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
