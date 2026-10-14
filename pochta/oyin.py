"""«Rost yoki jasorat» — ikki o'yinchili onlayn o'yin mantig'i.

HTTP'dan mustaqil: pochta.py so'rovlarni shu yerdagi funksiyalarga uzatadi.
Xonalar xotirada saqlanadi va XONA_MUDDAT o'tgach o'chadi.

O'yin bosqichlari:
  kutish  — xona ochilgan, ikkinchi o'yinchi hali kirmagan
  tanlov  — navbatdagi o'yinchi rost / jasorat / g'ildirakni tanlaydi
  karta   — navbatdagi o'yinchi javob yozadi yoki jasoratni bajaradi
  baho    — ikkinchi o'yinchi qabul qiladi yoki rad etadi
"""
import random
import secrets
import threading
import time

XONA_MUDDAT = 12 * 3600
MAX_XONA = 100
MAX_ISM = 20
MAX_JAVOB = 300
TARIX_SAQLASH = 50
TARIX_KORSATISH = 20
KOD_HARFLAR = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # O/0 va I/1 chalkashmasin
OCHKO = {"rost": 1, "jasorat": 2}
JARIMA = 1

# {u} — ikkinchi o'yinchining ismi; _ga, _da, _ni, _ning, _dan — kelishik shakllari
ROST = [
    "{u_da} birinchi nima yoqib qolgan edi?",
    "{u} bilan bog'liq eng kulgili xotirang qaysi?",
    "{u_ga} hali aytmagan bitta komplimentni yoz.",
    "{u_ning} qaysi odati seni jilmaytiradi?",
    "{u_ning} qaysi qilig'i ozgina jahlingni chiqaradi? Rostini ayt.",
    "Birga o'tkazgan eng yaxshi kuningiz qaysi?",
    "{u_ni} birinchi ko'rganingda nima deb o'ylading?",
    "Telefoningda {u} qanday nom bilan saqlangan?",
    "Agar bir kun {u_ning} o'rnida bo'lsang, birinchi nima qilarding?",
    "Sizning qo'shig'ingiz qaysi bo'lishi kerak?",
    "{u} bilan qayerga sayohat qilishni orzu qilasan?",
    "Oxirgi marta {u_ni} o'ylab qachon jilmayding?",
    "Agar {u} taom bo'lganida, qaysi taom bo'lardi? Nega?",
    "{u_dan} yashirgan eng kichik, eng zararsiz siring qaysi?",
    "{u_ning} eng chiroyli tomoni nima?",
    "{u_ga} qaysi kiyim eng ko'p yarashadi?",
    "{u} bilan birinchi suhbatingiz nima haqida edi?",
    "Bir kunga dunyoning istalgan joyiga {u} bilan borish mumkin bo'lsa — qayerga?",
    "{u_ning} qaysi gapi hali ham yodingda?",
    "Qachon birinchi marta «{u} menga yoqadi» deb o'ylading?",
    "{u} uchun qilgan eng shirin ishing qaysi?",
]
JASORAT = [
    "{u_ga} hozir ketma-ket 3 ta kompliment yoz — o'ylamasdan.",
    "{u_ga} ovozli xabarda biror qo'shiqdan bir qator kuylab yubor.",
    "Eng kulgili selfingni {u_ga} Telegram'da yubor.",
    "{u_ga} «seni sevaman»ni 3 xil tilda yoz.",
    "Keyingi 5 daqiqa {u_ga} faqat emoji bilan yoz.",
    "Telefoningda {u_ning} ismini yanada shirinroq nomga o'zgartir va skrinshot yubor.",
    "Birinchi uchrashuvingizni 3 so'z bilan tasvirla va {u_ga} yubor.",
    "Qog'ozga {u_ning} rasmini 30 soniyada chiz va suratini yubor.",
    "{u_ga} 4 qatorli she'r yoz. Hozir. Qofiya shart emas.",
    "{u_ga} qo'ng'iroq qil va 10 soniya faqat kulib tur — gapirmasdan.",
    "{u} bilan keyingi uchrashuv rejasini tuz va yubor: qayerga, qachon, nima qilamiz.",
    "{u_ga} bolalikdagi suratingni yubor.",
    "Ovozli xabarda {u_ni} 3 xil shirin laqab bilan chaqir.",
    "«Omina Times» muxbiri bo'lib {u_ga} bitta intervyu savoli ber.",
    "{u_ga} eng yoqtirgan qo'shig'ingni yubor va nega yoqishini bir gapda yoz.",
    "{u_ning} 3 ta yaxshi fazilatini faqat emoji bilan tasvirla va yubor.",
    "Ovozli xabarda {u_ga} 15 soniya davomida to'xtamasdan maqtov ayt.",
    "{u_ga} kelajakdagi uyingizni 3 gap bilan tasvirlab yoz.",
    "{u_ga} telefoningdagi eng shirin stikerni yubor.",
    "{u_ga} hozirgi kayfiyatingni bitta surat bilan ko'rsat — yuzing bilan.",
]
KARTALAR = {"rost": ROST, "jasorat": JASORAT}

_xonalar = {}
_qulf = threading.Lock()


class OyinXatosi(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato (HTTP kodi bilan)."""

    def __init__(self, kod, matn):
        super().__init__(matn)
        self.kod = kod
        self.matn = matn


# ── yordamchilar ────────────────────────────────────────────────────────────
def _ga(ism):
    oxiri = ism[-1:].lower()
    if oxiri == "k":
        return ism + "ka"
    if oxiri == "q":
        return ism + "qa"
    return ism + "ga"


def _karta_matni(shablon, ism):
    return shablon.format(
        u=ism, u_ga=_ga(ism), u_da=ism + "da", u_ni=ism + "ni", u_ning=ism + "ning", u_dan=ism + "dan"
    )


def _ism_tozala(ism):
    ism = " ".join(str(ism or "").split())[:MAX_ISM]
    if not ism:
        raise OyinXatosi(400, "Ismingni yoz.")
    return ism


def _boshqa(rol):
    return "b" if rol == "a" else "a"


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
    x["yangilandi"] = time.time()


def _keyingi_navbat(x):
    x["navbat"] = _boshqa(x["navbat"])
    x["bosqich"] = "tanlov"
    x["karta"] = None
    x["javob"] = None
    x["izoh"] = ""


def _karta_ol(x, tur, gildirak):
    ishlatilgan = x["ishlatilgan"][tur]
    toplam = KARTALAR[tur]
    qolgan = [i for i in range(len(toplam)) if i not in ishlatilgan]
    if not qolgan:
        ishlatilgan.clear()
        qolgan = list(range(len(toplam)))
    i = random.choice(qolgan)
    ishlatilgan.add(i)
    sherik = x["oyinchilar"][_boshqa(x["navbat"])]["ism"]
    x["karta_soni"] += 1
    x["karta"] = {"id": x["karta_soni"], "tur": tur, "matn": _karta_matni(toplam[i], sherik), "gildirak": gildirak}


def _tarixga(x, natija, ochko):
    o = x["oyinchilar"][x["navbat"]]
    x["tarix"].append({
        "kim": o["ism"], "rol": x["navbat"], "tur": x["karta"]["tur"], "savol": x["karta"]["matn"],
        "javob": x["javob"], "natija": natija, "ochko": ochko,
    })
    del x["tarix"][:-TARIX_SAQLASH]


# ── tashqi funksiyalar ──────────────────────────────────────────────────────
def holat(kod, token):
    with _qulf:
        x = _xona(kod)
        rol = _kim(x, token)
        return _korinish(x, rol)


def _korinish(x, rol):
    def oyinchi(r):
        o = x["oyinchilar"].get(r)
        return {"ism": o["ism"], "ochko": o["ochko"]} if o else None
    return {
        "kod": x["kod"], "men": rol, "versiya": x["versiya"],
        "oyinchilar": {"a": oyinchi("a"), "b": oyinchi("b")},
        "navbat": x["navbat"], "bosqich": x["bosqich"],
        "karta": x["karta"], "javob": x["javob"], "izoh": x["izoh"],
        "tarix": x["tarix"][-TARIX_KORSATISH:][::-1],
    }


def yangi(ism):
    ism = _ism_tozala(ism)
    with _qulf:
        _eskilarni_tozala()
        if len(_xonalar) >= MAX_XONA:
            raise OyinXatosi(503, "Hozir xonalar band. Birozdan keyin urinib ko'r.")
        while True:
            kod = "".join(secrets.choice(KOD_HARFLAR) for _ in range(4))
            if kod not in _xonalar:
                break
        token = secrets.token_hex(16)
        hozir = time.time()
        x = {
            "kod": kod, "yaratildi": hozir, "yangilandi": hozir, "versiya": 1,
            "oyinchilar": {"a": {"ism": ism, "token": token, "ochko": 0}, "b": None},
            "navbat": "b", "bosqich": "kutish", "karta": None, "javob": None, "izoh": "",
            "tarix": [], "karta_soni": 0, "ishlatilgan": {"rost": set(), "jasorat": set()},
        }
        _xonalar[kod] = x
        return {"kod": kod, "token": token, "holat": _korinish(x, "a")}


def qoshil(kod, ism):
    ism = _ism_tozala(ism)
    with _qulf:
        x = _xona(kod)
        if x["oyinchilar"]["b"]:
            raise OyinXatosi(409, "Bu xonada allaqachon ikki o'yinchi bor.")
        token = secrets.token_hex(16)
        x["oyinchilar"]["b"] = {"ism": ism, "token": token, "ochko": 0}
        x["navbat"] = "b"            # mehmon birinchi boshlaydi
        x["bosqich"] = "tanlov"
        _ozgardi(x)
        return {"kod": x["kod"], "token": token, "holat": _korinish(x, "b")}


def harakat(kod, token, tur, d):
    with _qulf:
        x = _xona(kod)
        rol = _kim(x, token)
        navbatim = rol == x["navbat"]
        bosqich = x["bosqich"]

        if tur == "tanla":
            if bosqich != "tanlov" or not navbatim:
                raise OyinXatosi(409, "Hozir sening navbating emas.")
            tanlov = d.get("tanlov")
            if tanlov == "gildirak":
                _karta_ol(x, random.choice(["rost", "jasorat"]), True)
            elif tanlov in KARTALAR:
                _karta_ol(x, tanlov, False)
            else:
                raise OyinXatosi(400, "Noma'lum tanlov.")
            x["bosqich"] = "karta"
            x["izoh"] = ""

        elif tur == "javob":
            if bosqich != "karta" or not navbatim or x["karta"]["tur"] != "rost":
                raise OyinXatosi(409, "Hozir javob yozib bo'lmaydi.")
            matn = " ".join(str(d.get("matn") or "").split())[:MAX_JAVOB]
            if not matn:
                raise OyinXatosi(400, "Javobni yoz.")
            x["javob"] = matn
            x["bosqich"] = "baho"

        elif tur == "bajardim":
            if bosqich != "karta" or not navbatim or x["karta"]["tur"] != "jasorat":
                raise OyinXatosi(409, "Hozir buni bosib bo'lmaydi.")
            x["javob"] = None
            x["bosqich"] = "baho"

        elif tur == "otkaz":
            if bosqich != "karta" or not navbatim:
                raise OyinXatosi(409, "Hozir o'tkazib bo'lmaydi.")
            o = x["oyinchilar"][rol]
            oldin = o["ochko"]
            o["ochko"] = max(0, oldin - JARIMA)          # ochko manfiy bo'lmaydi
            _tarixga(x, "otkazildi", o["ochko"] - oldin)
            _keyingi_navbat(x)

        elif tur == "baho":
            if bosqich != "baho" or navbatim:
                raise OyinXatosi(409, "Hozir baholash navbati senda emas.")
            if d.get("qabul") is True:
                ball = OCHKO[x["karta"]["tur"]]
                x["oyinchilar"][x["navbat"]]["ochko"] += ball
                _tarixga(x, "qabul", ball)
                _keyingi_navbat(x)
            else:
                x["bosqich"] = "karta"
                x["javob"] = None
                x["izoh"] = "rad"
        else:
            raise OyinXatosi(400, "Noma'lum harakat.")

        _ozgardi(x)
        return _korinish(x, rol)
