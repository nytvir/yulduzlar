"""«Rost yoki jasorat» — ikki o'yinchili onlayn o'yin mantig'i.

HTTP'dan mustaqil: pochta.py so'rovlarni shu yerdagi funksiyalarga uzatadi.
Xonalar xotirada saqlanadi va XONA_MUDDAT o'tgach o'chadi.

Rejimlar:
  odatiy   — 1-qism: savol/jasorat tayyor to'plamdan olinadi
  ikkinchi — 2-qism: yangi to'plam
  shaxsiy — savolni yoki jasoratni sherik o'zi yozadi

O'yin bosqichlari:
  kutish  — xona ochilgan, ikkinchi o'yinchi hali kirmagan
  tanlov  — navbatdagi o'yinchi rost / jasorat / g'ildirakni tanlaydi
  yozish  — (faqat shaxsiy) sherik savol yoki jasorat matnini yozadi
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
MAX_SAVOL = 200
REJIMLAR = ("odatiy", "ikkinchi", "shaxsiy")
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

# ── 2-qism: yangi to'plam (1-qism bilan takrorlanmaydi) ──────────────────────
ROST2 = [
    "{u_ning} qaysi gapidan keyin «mana shu odam» deb o'ylading?",
    "{u} bilan bo'lgan eng romantik lahzang qaysi?",
    "{u_ga} hali aytmagan bitta orzuing bormi?",
    "{u_ning} qaysi kiyimda eng chiroyli ko'rinishini aytib ber.",
    "{u} bilan bog'liq eng uyatli, lekin kulgili holating qaysi?",
    "Bir kunga {u} bilan o'rningizni almashtirsangiz, birinchi nima qilarding?",
    "{u_ning} ovozini qaysi paytda eng yaxshi ko'rasan?",
    "{u_dan} qachon eng ko'p faxrlangansan?",
    "{u} haqida birinchi marta kimga gapirib bergansan va nima degansan?",
    "{u_ga} qaysi qo'shiqni bag'ishlagan bo'larding?",
    "{u} bilan qaysi filmni qayta ko'rishni xohlarding?",
    "{u_ning} qaysi tomonini hech kim bilmaydi, faqat sen bilasan?",
    "Oxirgi marta {u_dan} rashk qilganmisan? Rostini ayt.",
    "{u} uchun qila oladigan eng aqldan ozgan ishing nima bo'lardi?",
    "{u} bilan 10 yildan keyin qayerda bo'lishni xohlaysan?",
    "{u_ning} qaysi odatini yashirincha takrorlaysan?",
    "{u_ga} qanday laqab qo'ygan bo'larding — va nega?",
    "Bugun {u_ning} nimasi senga eng yoqdi?",
    "{u} bilan hali hech qachon qilmagan, lekin qilmoqchi bo'lgan narsang?",
    "{u_ni} uch so'z bilan tasvirla.",
    "{u_ga} qachon «kechirasan» deyishing kerak edi, lekin aytmagansan?",
    "{u_ning} tayyorlagan narsalaridan qaysi biri eng mazali?",
]
JASORAT2 = [
    "{u_ga} 30 soniyalik ovozli xabarda sevgi izhor qil — xuddi birinchi martadek.",
    "{u_ning} ismini 5 xil ohangda ovozli xabarda ayt.",
    "{u_ga} ertangi kun uchun 3 ta kichik va'da yoz.",
    "{u} bilan eng sevimli suratingizni yubor va nega yoqishini yoz.",
    "{u_ga} she'r yoz — har qatori uning ismidagi bir harf bilan boshlansin.",
    "{u_ga} eng kulgili ovozingda «seni sevaman» de.",
    "Bugungi kuningni 3 ta emoji bilan tasvirla va {u_ga} tushuntirib ber.",
    "Ovozli xabarda {u_ga} oddiy bir narsani — choynak, qalam — televizordagidek reklama qilib ber.",
    "{u} uchun 1 daqiqada kichik sovg'a o'ylab top va qachon berishingni yoz.",
    "{u_ga} hozirgi kayfiyatingga mos qo'shiq yubor.",
    "{u_ning} 5 ta yaxshi fazilatini yoz — birontasi takrorlanmasin.",
    "Keyingi navbatgacha {u_ga} faqat savol bilan javob ber.",
    "Birinchi uchrashuvingizni {u_ga} ertakdek hikoya qilib ber: «Bir bor ekan…»",
    "{u} bilan kelajakdagi bitta kuningizni ertalabdan kechgacha rejalashtir.",
    "{u_dan} kechirim so'ra — hech narsa uchun, shunchaki chiroyli qilib.",
    "Telefoningdagi {u_ning} eng yaxshi suratini yubor va unga sarlavha yoz.",
    "{u_ni} videoqo'ng'iroqqa chaqir va 15 soniya gapirmasdan qarab tur.",
    "«Omina Times» uchun {u} haqida bitta gazeta sarlavhasi yoz.",
    "{u} bugun qilgan eng yaxshi ishni sport sharhlovchisidek ovozli xabarda maqta.",
    "Eng shirin laqabingni o'ylab top va bugun {u_ni} shunday chaqir.",
]

# rejim → to'plam; «shaxsiy» rejimda matnni sherik yozadi, to'plam kerak emas
TOPLAMLAR = {
    "odatiy":   {"rost": ROST,  "jasorat": JASORAT},
    "ikkinchi": {"rost": ROST2, "jasorat": JASORAT2},
}
TURLAR = ("rost", "jasorat")

_xonalar = {}
_qulf = threading.Lock()

# pochta.py o'rnatadi: tarix yozuvini doimiy arxivga (diskka) saqlaydigan funksiya.
# O'yin mantig'i faylga bog'lanib qolmasligi uchun shu yerda faqat chaqiriladi.
ARXIVGA = None


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


def ism_tozala(ism):
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
    toplam = TOPLAMLAR[x["rejim"]][tur]
    qolgan = [i for i in range(len(toplam)) if i not in ishlatilgan]
    if not qolgan:
        ishlatilgan.clear()
        qolgan = list(range(len(toplam)))
    i = random.choice(qolgan)
    ishlatilgan.add(i)
    sherik = x["oyinchilar"][_boshqa(x["navbat"])]["ism"]
    x["karta_soni"] += 1
    x["karta"] = {"id": x["karta_soni"], "tur": tur, "matn": _karta_matni(toplam[i], sherik),
                  "gildirak": gildirak, "muallif": None}


def _karta_bosh(x, tur, gildirak):
    """Shaxsiy rejim: karta turi tanlandi, matnini sherik keyin yozadi."""
    x["karta_soni"] += 1
    x["karta"] = {"id": x["karta_soni"], "tur": tur, "matn": None, "gildirak": gildirak, "muallif": None}


def _tarixga(x, natija, ochko):
    o = x["oyinchilar"][x["navbat"]]
    yozuv = {
        "kim": o["ism"], "rol": x["navbat"], "tur": x["karta"]["tur"], "savol": x["karta"]["matn"],
        "muallif": x["karta"]["muallif"], "javob": x["javob"], "natija": natija, "ochko": ochko,
    }
    x["tarix"].append(yozuv)
    del x["tarix"][:-TARIX_SAQLASH]
    if ARXIVGA:
        oy = x["oyinchilar"]
        try:
            ARXIVGA(dict(yozuv, xona=x["kod"], vaqt=time.time(), rejim=x["rejim"],
                         oyinchilar=[oy["a"]["ism"], oy["b"]["ism"] if oy["b"] else ""]))
        except Exception as e:  # arxiv xatosi o'yinni to'xtatmasin
            print("arxiv xatosi:", type(e).__name__, flush=True)


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
        "kod": x["kod"], "men": rol, "versiya": x["versiya"], "rejim": x["rejim"],
        "oyinchilar": {"a": oyinchi("a"), "b": oyinchi("b")},
        "navbat": x["navbat"], "bosqich": x["bosqich"],
        "karta": x["karta"], "javob": x["javob"], "izoh": x["izoh"],
        "tarix": x["tarix"][-TARIX_KORSATISH:][::-1],
    }


def yangi(d):
    ism = ism_tozala(d.get("ism"))
    rejim = d.get("rejim") if d.get("rejim") in REJIMLAR else "odatiy"
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
            "kod": kod, "yaratildi": hozir, "yangilandi": hozir, "versiya": 1, "rejim": rejim,
            "oyinchilar": {"a": {"ism": ism, "token": token, "ochko": 0}, "b": None},
            "navbat": "b", "bosqich": "kutish", "karta": None, "javob": None, "izoh": "",
            "tarix": [], "karta_soni": 0, "ishlatilgan": {"rost": set(), "jasorat": set()},
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
            gildirak = tanlov == "gildirak"
            if gildirak:
                tanlov = random.choice(["rost", "jasorat"])
            elif tanlov not in TURLAR:
                raise OyinXatosi(400, "Noma'lum tanlov.")
            if x["rejim"] == "shaxsiy":
                _karta_bosh(x, tanlov, gildirak)
                x["bosqich"] = "yozish"
            else:
                _karta_ol(x, tanlov, gildirak)
                x["bosqich"] = "karta"
            x["izoh"] = ""

        elif tur == "savol":
            if bosqich != "yozish" or navbatim:
                raise OyinXatosi(409, "Hozir savol yozish navbati senda emas.")
            matn = " ".join(str(d.get("matn") or "").split())[:MAX_SAVOL]
            if not matn:
                raise OyinXatosi(400, "Savolni yoz.")
            x["karta"]["matn"] = matn
            x["karta"]["muallif"] = x["oyinchilar"][rol]["ism"]
            x["bosqich"] = "karta"

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

# ── qayta ishga tushganda xonalar yo'qolmasin ───────────────────────────────
def eksport():
    """Ochiq xonalarni JSON'ga yaroqli ko'rinishda qaytaradi (to'plamlar — ro'yxat)."""
    with _qulf:
        _eskilarni_tozala()
        return {kod: dict(x, ishlatilgan={t: sorted(v) for t, v in x["ishlatilgan"].items()})
                for kod, x in _xonalar.items()}


def import_(malumot):
    with _qulf:
        for kod, x in (malumot or {}).items():
            x["ishlatilgan"] = {t: set(v) for t, v in x.get("ishlatilgan", {}).items()}
            x.setdefault("rejim", "odatiy")
            _xonalar[kod] = x
        _eskilarni_tozala()
