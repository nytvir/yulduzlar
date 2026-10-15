"""«Telepatiya» — ikki o'yinchili hamkorlik o'yini.

Ikkalasi bir vaqtda, yashirin holda bittadan so'z yozadi. So'zlar birdan
ochiladi: bir xil bo'lsa — topildi. Har xil bo'lsa, keyingi raundda ikkalasi
oldingi ikki so'zni bog'laydigan so'z yozadi. Aytilgan so'zni qayta aytib bo'lmaydi.

Bosqichlar:
  kutish   — ikkinchi o'yinchi hali kirmagan
  yozish   — joriy raundda so'zlar yozilmoqda (sherikning so'zi yashirin)
  ochildi  — ikkala so'z ochildi; «davom» bosilishini kutadi
  tugadi   — barcha mavzular o'ynaldi
"""
import random
import re
import secrets
import threading
import time

from oyin import KOD_HARFLAR, MAX_XONA, XONA_MUDDAT, OyinXatosi, ism_tozala

MAVZU_SONI = 5
MAX_RAUND = 6
ENG_KOP_OCHKO = 5                 # 1-raundda topilsa; har raundda 1 tadan kamayadi, kamida 1
MAX_SOZ = 24

MAVZULAR = [
    "Sevgi", "Toshkent", "Bizning birinchi uchrashuv", "Shirinlik", "Dam olish kuni",
    "Kino", "Yoz", "Sovg'a", "Kelajak", "Uy", "Musiqa", "Sayohat", "Bayram",
    "Ertalab", "Omina Times", "Kechki ovqat", "Bolalik", "Qish",
]

_xonalar = {}
_qulf = threading.Lock()

# pochta.py o'rnatadi: tugagan har bir mavzuni doimiy arxivga yozadi
ARXIVGA = None


# ── yordamchilar ────────────────────────────────────────────────────────────
def solishtir(soz):
    """«O'rik», «o‘rik», «ORIK» — bir xil so'z hisoblanadi."""
    s = soz.lower()
    s = re.sub(r"[‘’`ʻʼ']", "", s)
    s = re.sub(r"[^\w\s-]", "", s)
    return " ".join(s.replace("-", " ").split())


def _ochko(raund):
    return max(1, ENG_KOP_OCHKO + 1 - raund)    # 1-raund: 5, 2: 4 … 5 va undan keyin: 1


def _eskilarni_tozala():
    hozir = time.time()
    for kod in [k for k, x in _xonalar.items() if hozir - x["yaratildi"] > XONA_MUDDAT]:
        del _xonalar[kod]


def _xona(kod):
    x = _xonalar.get(str(kod or "").upper())
    if not x:
        raise OyinXatosi(404, "Bunday xona topilmadi yoki muddati tugagan.")
    return x


def _kim(x, token):
    for rol in ("a", "b"):
        o = x["oyinchilar"].get(rol)
        if o and token and secrets.compare_digest(o["token"], str(token)):
            return rol
    raise OyinXatosi(403, "Bu xonaga ruxsating yo'q.")


def _ozgardi(x):
    x["versiya"] += 1


def _yangi_oyin(x):
    x["mavzular"] = random.sample(MAVZULAR, MAVZU_SONI)
    x["mavzu"] = 0
    x["ochko"] = 0
    x["natijalar"] = []
    _yangi_mavzu(x)


def _yangi_mavzu(x):
    x["raund"] = 1
    x["zanjir"] = []
    x["taqiq"] = set()
    x["sozlar"] = {"a": None, "b": None}
    x["topildi"] = False
    x["bosqich"] = "yozish"


def _mavzu_tugadi(x, topildi):
    ball = _ochko(x["raund"]) if topildi else 0
    x["ochko"] += ball
    x["topildi"] = topildi
    natija = {
        "mavzu": x["mavzular"][x["mavzu"]], "zanjir": list(x["zanjir"]),
        "topildi": topildi, "raund": x["raund"], "ochko": ball,
    }
    x["natijalar"].append(natija)
    if ARXIVGA:
        oy = x["oyinchilar"]
        a, b = oy["a"]["ism"], oy["b"]["ism"]
        zanjir = " → ".join(f"{q['a']} / {q['b']}" for q in natija["zanjir"])
        try:
            ARXIVGA({
                "xona": x["kod"], "vaqt": time.time(), "oyinchilar": [a, b],
                "kim": f"{a} va {b}", "tur": "telepatiya", "savol": "Mavzu: " + natija["mavzu"],
                "javob": zanjir + (f"  ✓ {natija['raund']}-raundda topildi" if topildi else "  ✗ topilmadi"),
                "natija": "qabul" if topildi else "otkazildi", "ochko": ball,
            })
        except Exception as e:
            print("arxiv xatosi:", type(e).__name__, flush=True)


def _korinish(x, rol):
    sherik = "b" if rol == "a" else "a"

    def oyinchi(r):
        o = x["oyinchilar"].get(r)
        return {"ism": o["ism"]} if o else None

    holat = {
        "kod": x["kod"], "men": rol, "versiya": x["versiya"], "bosqich": x["bosqich"],
        "oyinchilar": {"a": oyinchi("a"), "b": oyinchi("b")},
        "max_ochko": MAVZU_SONI * _ochko(1), "mavzu_soni": MAVZU_SONI, "max_raund": MAX_RAUND,
    }
    if x["bosqich"] == "kutish":
        return holat
    holat.update({
        "mavzu_n": x["mavzu"] + 1, "mavzu": x["mavzular"][x["mavzu"]], "raund": x["raund"],
        "ochko": x["ochko"], "zanjir": x["zanjir"], "topildi": x["topildi"],
        "natijalar": x["natijalar"],
        "mening_sozim": x["sozlar"][rol],
        "sherik_yozdimi": x["sozlar"][sherik] is not None,   # sherikning so'zi o'zi yashirin
    })
    return holat


# ── tashqi funksiyalar ──────────────────────────────────────────────────────
def holat(kod, token):
    with _qulf:
        x = _xona(kod)
        return _korinish(x, _kim(x, token))


def yangi(d):
    ism = ism_tozala(d.get("ism"))
    with _qulf:
        _eskilarni_tozala()
        if len(_xonalar) >= MAX_XONA:
            raise OyinXatosi(503, "Hozir xonalar band. Birozdan keyin urinib ko'r.")
        while True:
            kod = "".join(secrets.choice(KOD_HARFLAR) for _ in range(4))
            if kod not in _xonalar:
                break
        token = secrets.token_hex(16)
        x = {
            "kod": kod, "yaratildi": time.time(), "versiya": 1, "bosqich": "kutish",
            "oyinchilar": {"a": {"ism": ism, "token": token}, "b": None},
        }
        _xonalar[kod] = x
        return {"kod": kod, "token": token, "holat": _korinish(x, "a")}


def qoshil(kod, ism):
    ism = ism_tozala(ism)
    with _qulf:
        x = _xona(kod)
        if x["oyinchilar"]["b"]:
            raise OyinXatosi(409, "Bu xonada allaqachon ikki o'yinchi bor.")
        token = secrets.token_hex(16)
        x["oyinchilar"]["b"] = {"ism": ism, "token": token}
        _yangi_oyin(x)
        _ozgardi(x)
        return {"kod": x["kod"], "token": token, "holat": _korinish(x, "b")}


def harakat(kod, token, tur, d):
    with _qulf:
        x = _xona(kod)
        rol = _kim(x, token)

        if tur == "soz":
            if x["bosqich"] != "yozish":
                raise OyinXatosi(409, "Hozir so'z yozib bo'lmaydi.")
            if x["sozlar"][rol] is not None:
                raise OyinXatosi(409, "So'zing allaqachon yuborilgan.")
            soz = " ".join(str(d.get("soz") or "").split())[:MAX_SOZ]
            kalit = solishtir(soz)
            if not kalit:
                raise OyinXatosi(400, "Bitta so'z yoz.")
            if kalit in x["taqiq"]:
                raise OyinXatosi(409, "Bu so'z bu mavzuda allaqachon aytilgan. Boshqasini o'yla.")
            x["sozlar"][rol] = soz
            if x["sozlar"]["a"] is not None and x["sozlar"]["b"] is not None:
                a, b = x["sozlar"]["a"], x["sozlar"]["b"]
                x["zanjir"].append({"a": a, "b": b})
                x["taqiq"].update({solishtir(a), solishtir(b)})
                x["bosqich"] = "ochildi"
                if solishtir(a) == solishtir(b):
                    _mavzu_tugadi(x, True)
                elif x["raund"] >= MAX_RAUND:
                    _mavzu_tugadi(x, False)

        elif tur == "davom":
            # Ikkalasi ham bosishi mumkin: faqat ko'rsatilgan raundga tegishli birinchi bosish ishlaydi
            belgi = f"{x.get('mavzu', 0) + 1}:{x.get('raund', 0)}"
            if x["bosqich"] != "ochildi" or str(d.get("belgi")) != belgi:
                return _korinish(x, rol)
            mavzu_yopildi = len(x["natijalar"]) > x["mavzu"]
            if not mavzu_yopildi:
                x["raund"] += 1
                x["sozlar"] = {"a": None, "b": None}
                x["bosqich"] = "yozish"
            elif x["mavzu"] + 1 < MAVZU_SONI:
                x["mavzu"] += 1
                _yangi_mavzu(x)
            else:
                x["bosqich"] = "tugadi"

        elif tur == "qayta":
            if x["bosqich"] != "tugadi":
                raise OyinXatosi(409, "O'yin hali tugamagan.")
            _yangi_oyin(x)

        else:
            raise OyinXatosi(400, "Noma'lum harakat.")

        _ozgardi(x)
        return _korinish(x, rol)

# ── qayta ishga tushganda xonalar yo'qolmasin ───────────────────────────────
def eksport():
    with _qulf:
        _eskilarni_tozala()
        return {kod: dict(x, taqiq=sorted(x["taqiq"])) if "taqiq" in x else dict(x)
                for kod, x in _xonalar.items()}


def import_(malumot):
    with _qulf:
        for kod, x in (malumot or {}).items():
            if "taqiq" in x:
                x["taqiq"] = set(x["taqiq"])
            _xonalar[kod] = x
        _eskilarni_tozala()
