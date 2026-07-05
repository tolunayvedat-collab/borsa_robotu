import sys
import os

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

def guvenli_giris_bekle(mesaj=""):
    if not os.getenv("GITHUB_ACTIONS") and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        try:
            return input(mesaj)
        except Exception:
            pass
    return ""

import time
import json
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- KÜTÜPHANE KONTROLÜ ---
try:
    import pandas as pd
    import yfinance as yf
    import requests
    from zoneinfo import ZoneInfo
    from prettytable import PrettyTable
    from colorama import Fore, Back, Style, init
    from dotenv import load_dotenv
except ImportError as e:
    print("=" * 60)
    print("❌ EKSİK KÜTÜPHANE HATASI")
    print("=" * 60)
    print(f"\nHata: {e}\n")
    print("Aşağıdaki komutu çalıştırıp gerekli kütüphaneleri kur:\n")
    print("  pip install pandas yfinance requests prettytable colorama python-dotenv tzdata\n")
    print("=" * 60)
    guvenli_giris_bekle("Kapatmak için Enter tuşuna basın...")
    sys.exit(1)

# --- SAAT DİLİMİ KONTROLÜ ---
try:
    ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
    NEWYORK_TZ = ZoneInfo("America/New_York")
except Exception as e:
    print("=" * 60)
    print("❌ SAAT DİLİMİ (tzdata) HATASI")
    print("=" * 60)
    print(f"\nHata: {e}\n")
    print("Windows'ta saat dilimi veritabanı eksik olabilir. Şu komutu çalıştır:\n")
    print("  pip install tzdata\n")
    print("Kurulumdan sonra programı tekrar başlat.")
    print("=" * 60)
    guvenli_giris_bekle("Kapatmak için Enter tuşuna basın...")
    sys.exit(1)

# --- ORTAM DEĞİŞKENLERİ (.env dosyasından okunur) ---
load_dotenv()

# --- HATA LOG VE DOSYALAR ---
LOG_DOSYASI = "hata_log.txt"
SINYAL_KAYIT_DOSYASI = "gonderilen_sinyaller.json"
CONFIG_DOSYASI = "config.json"
DASHBOARD_DOSYASI = "dashboard.html"

# Varsayılan Değerler (Eğer config.json yüklenemezse kullanılır)
VARSAYILAN_PIYASALAR = [
    {
        "id": "TR", "ad": "TR", "telegram_ad": "BIST",
        "semboller": [
            "THYAO.IS", "EREGL.IS", "AKBNK.IS", "ASELS.IS", "TUPRS.IS",
            "SAHOL.IS", "BIMAS.IS", "YKBNK.IS", "KCHOL.IS", "ISCTR.IS",
            "GARAN.IS", "SISE.IS", "PETKM.IS", "SASA.IS", "HEKTS.IS",
            "ASTOR.IS", "KONTR.IS", "SMRTG.IS", "ALARK.IS", "ODAS.IS"
        ]
    },
    {
        "id": "US", "ad": "US", "telegram_ad": "ABD",
        "semboller": [
            "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "AMD", "META",
            "GOOGL", "NFLX", "COIN", "INTC", "QCOM", "BABA", "XOM"
        ]
    },
    {
        "id": "KR", "ad": "KR", "telegram_ad": "KR",
        "semboller": [
            "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "XRP-USD",
            "LINK-USD", "BNB-USD", "ADA-USD", "DOT-USD"
        ]
    }
]

# --- YAPILANDIRMA YÜKLEME ---
def config_yukle():
    yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_DOSYASI)
    if os.path.exists(yol):
        try:
            with open(yol, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                markets = cfg.get("markets", VARSAYILAN_PIYASALAR)
                verbose = cfg.get("verbose", False)
                interval = cfg.get("scan_interval_minutes", 15)
                return markets, verbose, interval
        except Exception as e:
            print(f"Yapılandırma yüklenirken hata oluştu: {e}. Varsayılan ayarlar kullanılacak.")
    return VARSAYILAN_PIYASALAR, False, 15

PIYASALAR, VERBOSE, TARAMA_ARALIGI = config_yukle()

# --- HATA VE SİNYAL İŞLEMLERİ ---
def hata_kaydet(hata_mesaji):
    try:
        yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_DOSYASI)
        with open(yol, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Hata:\n{hata_mesaji}\n")
            f.write(f"{'='*50}\n")
    except Exception as e:
        print(f"Log yazma hatası: {e}")

# Colorama başlat
try:
    init(autoreset=True)
except Exception as e:
    print(f"Colorama hatası: {e}")
    init()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print(Fore.YELLOW + "[!] UYARI: TELEGRAM_TOKEN / TELEGRAM_CHAT_ID .env dosyasında bulunamadı. "
                         "Telegram bildirimleri devre dışı kalacak." + Style.RESET_ALL)

def _sinyal_dosya_yolu():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), SINYAL_KAYIT_DOSYASI)

def sinyalleri_yukle():
    try:
        yol = _sinyal_dosya_yolu()
        if os.path.exists(yol):
            with open(yol, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except Exception as e:
        if VERBOSE:
            print(f"Sinyal kayıt okuma hatası: {e}")
    return set()

def sinyalleri_kaydet(sinyal_seti):
    try:
        yol = _sinyal_dosya_yolu()
        with open(yol, "w", encoding="utf-8") as f:
            json.dump(list(sinyal_seti), f)
    except Exception as e:
        if VERBOSE:
            print(f"Sinyal kayıt yazma hatası: {e}")

gonderilen_sinyaller = sinyalleri_yukle()

def bildirim_gonder(mesaj):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "HTML"}, timeout=3)
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")

# --- TEKNİK ANALİZ İNDİKATÖRLERİ ---
def rsi_hesapla(series, period=14):
    try:
        if len(series) < period + 1:
            return pd.Series(50, index=series.index)
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rsi = pd.Series(index=series.index, dtype=float)
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.where(~((loss == 0) & (gain > 0)), 100)
        rsi = rsi.where(~((loss == 0) & (gain == 0)), 50)
        return rsi.fillna(50)
    except Exception as e:
        print(f"RSI hatası: {e}")
        return pd.Series(50, index=series.index)

def atr_hesapla(df, period=14):
    try:
        high = df['High']
        low = df['Low']
        prev_close = df['Close'].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr
    except Exception as e:
        print(f"ATR hatası: {e}")
        return pd.Series(0, index=df.index)

def bollinger_genislik_hesapla(df, period=20, std_carpani=2):
    try:
        orta = df['Close'].rolling(window=period).mean()
        std = df['Close'].rolling(window=period).std()
        ust = orta + std_carpani * std
        alt = orta - std_carpani * std
        genislik_yuzde = (ust - alt) / orta * 100
        return genislik_yuzde
    except Exception as e:
        print(f"Bollinger hatası: {e}")
        return pd.Series(999, index=df.index)

def obv_hesapla(df):
    try:
        yon = df['Close'].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv = (yon * df['Volume']).fillna(0).cumsum()
        return obv
    except Exception as e:
        print(f"OBV hatası: {e}")
        return pd.Series(0, index=df.index)

def dmi_adx_hesapla(df, period=14):
    try:
        high = df['High']
        low = df['Low']
        prev_high = high.shift(1)
        prev_low = low.shift(1)
        prev_close = df['Close'].shift(1)

        artis_hareketi = high - prev_high
        azalis_hareketi = prev_low - low

        plus_dm = ((artis_hareketi > azalis_hareketi) & (artis_hareketi > 0)) * artis_hareketi
        minus_dm = ((azalis_hareketi > artis_hareketi) & (azalis_hareketi > 0)) * azalis_hareketi

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)

        tr_smooth = tr.rolling(window=period).mean()
        plus_dm_smooth = plus_dm.rolling(window=period).mean()
        minus_dm_smooth = minus_dm.rolling(window=period).mean()

        di_plus = 100 * (plus_dm_smooth / tr_smooth.replace(0, pd.NA))
        di_minus = 100 * (minus_dm_smooth / tr_smooth.replace(0, pd.NA))
        
        di_plus = di_plus.fillna(0)
        di_minus = di_minus.fillna(0)
        
        sum_di = di_plus + di_minus
        diff_di = (di_plus - di_minus).abs()
        
        dx = 100 * (diff_di / sum_di.replace(0, pd.NA))
        dx = dx.fillna(0)
        
        adx = dx.rolling(window=period).mean().fillna(20)
        return di_plus, di_minus, adx
    except Exception as e:
        print(f"DMI/ADX hatası: {e}")
        return pd.Series(0, index=df.index), pd.Series(0, index=df.index), pd.Series(20, index=df.index)

def macd_hesapla(series, fast_period=12, slow_period=26, signal_period=9):
    try:
        fast_ema = series.ewm(span=fast_period, adjust=False).mean()
        slow_ema = series.ewm(span=slow_period, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist
    except Exception as e:
        print(f"MACD hatası: {e}")
        return pd.Series(0, index=series.index), pd.Series(0, index=series.index), pd.Series(0, index=series.index)

def ucgen_tipi_belirle(df, pencere=20):
    try:
        if len(df) < pencere * 2:
            return "veri_yok"
        alt = df['Low'].iloc[-pencere:]
        ust = df['High'].iloc[-pencere:]
        yarim = pencere // 2
        ilk_alt = alt.iloc[:yarim].min()
        son_alt = alt.iloc[yarim:].min()
        ilk_ust = ust.iloc[:yarim].max()
        son_ust = ust.iloc[yarim:].max()

        dipler_yukseliyor = son_alt > ilk_alt * 1.005
        tepeler_sabit_dusuk = son_ust <= ilk_ust * 1.005
        tepeler_alcaliyor = son_ust < ilk_ust * 0.995
        dipler_sabit_yuksek = son_alt >= ilk_alt * 0.995

        if dipler_yukseliyor and tepeler_sabit_dusuk:
            return "yukselen"
        elif tepeler_alcaliyor and dipler_sabit_yuksek:
            return "alcalan"
        else:
            return "notr"
    except Exception as e:
        print(f"Üçgen tipi hatası: {e}")
        return "veri_yok"

# --- DOVİZ KURLARI ---
def guncel_dolar_kuru_al():
    try:
        kur_ticker = yf.Ticker("USDTRY=X")
        kur_df = kur_ticker.history(period="2d", timeout=3)
        if not kur_df.empty:
            return kur_df['Close'].iloc[-1]
    except Exception as e:
        if VERBOSE:
            print(f"Dolar kuru hatası: {e}")
    return 46.80

def guncel_euro_kuru_al():
    try:
        kur_ticker = yf.Ticker("EURTRY=X")
        kur_df = kur_ticker.history(period="2d", timeout=3)
        if not kur_df.empty:
            return kur_df['Close'].iloc[-1]
    except Exception as e:
        if VERBOSE:
            print(f"Euro kuru hatası: {e}")
    return 50.50

def deger_formatla(deger):
    try:
        if deger >= 1000000:
            return f"{deger/1000000:.1f}M"
        elif deger >= 1000:
            return f"{deger:.0f}"
        else:
            return f"{deger:.1f}"
    except:
        return "0"

def piyasa_acik_mi(piyasa_id):
    try:
        if piyasa_id == "KR":
            return True

        if piyasa_id == "TR":
            simdi = datetime.now(ISTANBUL_TZ)
            gun = simdi.weekday()
            saat_dakika = simdi.strftime("%H:%M")
            if gun in [5, 6]:
                return False
            return "10:00" <= saat_dakika <= "18:15"

        if piyasa_id == "US":
            simdi_ny = datetime.now(NEWYORK_TZ)
            gun = simdi_ny.weekday()
            saat_dakika = simdi_ny.strftime("%H:%M")
            if gun in [5, 6]:
                return False
            return "09:30" <= saat_dakika <= "16:00"

        return False
    except Exception as e:
        print(f"Piyasa kontrol hatası: {e}")
        return False

def tv_linki_olustur(symbol, piyasa_id):
    if piyasa_id == "TR":
        return f"https://tr.tradingview.com/symbols/BIST-{symbol}/"
    elif piyasa_id == "US":
        return f"https://tr.tradingview.com/symbols/{symbol}/"
    elif piyasa_id == "KR":
        base_crypto = symbol.replace("TRY", "").replace("USD", "")
        return f"https://tr.tradingview.com/symbols/BINANCE-{base_crypto}USDT/"
    return f"https://tr.tradingview.com/symbols/{symbol}/"

# --- TEK TEK SEMBOL TARAMA FONKSİYONU (THREAD İÇİN) ---
def sembol_tara(ticker, piyasa, usd_try, acik_mi):
    try:
        df = yf.Ticker(ticker).history(period="1y", interval="1d", timeout=5)
        if df.empty or len(df) < 30:
            return None
        
        yeterli_veri_var = len(df) >= 200

        son_kapanis = df['Close'].iloc[-1]
        onceki_kapanis = df['Close'].iloc[-2]
        degisim = round(((son_kapanis - onceki_kapanis) / onceki_kapanis) * 100, 2)

        df['RSI'] = rsi_hesapla(df['Close'], 14)
        rsi_val = round(df['RSI'].iloc[-1], 2) if not pd.isna(df['RSI'].iloc[-1]) else 50

        df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
        ema21_val = df['EMA21'].iloc[-1]

        trend_yukselis = None
        if yeterli_veri_var:
            ema50_val = df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
            ema200_val = df['Close'].ewm(span=200, adjust=False).mean().iloc[-1]
            trend_yukselis = bool(ema50_val > ema200_val)

        if len(df) >= 11:
            roc10 = round(((son_kapanis - df['Close'].iloc[-11]) / df['Close'].iloc[-11]) * 100, 2)
        else:
            roc10 = 0.0

        df['ATR'] = atr_hesapla(df, 14)
        atr_val = df['ATR'].iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            atr_val = son_kapanis * 0.02

        hacim_ort = df['Volume'].rolling(window=20).mean().iloc[-1]
        hacim_yuksek = df['Volume'].iloc[-1] > hacim_ort * 1.2

        # Bollinger sıkışma (squeeze)
        sikisma = False
        if len(df) >= 130:
            genislik = bollinger_genislik_hesapla(df, 20, 2)
            gecerli_genislik = genislik.dropna()
            if len(gecerli_genislik) >= 120:
                esik = gecerli_genislik.iloc[-120:].quantile(0.2)
                sikisma = bool(genislik.iloc[-1] <= esik)

        # Hacim kuruması
        hacim_kurumus = False
        if len(df) >= 25:
            son5_hacim = df['Volume'].iloc[-6:-1].mean()
            hacim_kurumus = bool(son5_hacim < hacim_ort * 0.7)

        # OBV birikim/dağıtım
        birikim = False
        dagitim = False
        if len(df) >= 15:
            obv = obv_hesapla(df)
            obv_degisim = obv.iloc[-1] - obv.iloc[-11]
            fiyat_degisim_10 = abs((son_kapanis - df['Close'].iloc[-11]) / df['Close'].iloc[-11] * 100)
            birikim = bool(obv_degisim > 0 and fiyat_degisim_10 < 3)
            dagitim = bool(obv_degisim < 0 and fiyat_degisim_10 < 3)

        # DI+/DI- (DMI) ve ADX (Trend Gücü)
        di_plus, di_minus, adx = dmi_adx_hesapla(df, 14)
        di_plus_val = di_plus.iloc[-1]
        di_minus_val = di_minus.iloc[-1]
        di_yukselis_baskin = bool(di_plus_val > di_minus_val)
        adx_val = round(adx.iloc[-1], 2) if not pd.isna(adx.iloc[-1]) else 20.0

        # MACD (Trend Momentum)
        macd_line, signal_line, macd_hist = macd_hesapla(df['Close'], 12, 26, 9)
        macd_val = round(macd_line.iloc[-1], 4) if not pd.isna(macd_line.iloc[-1]) else 0.0
        macd_sig = round(signal_line.iloc[-1], 4) if not pd.isna(signal_line.iloc[-1]) else 0.0
        macd_hist_val = round(macd_hist.iloc[-1], 4) if not pd.isna(macd_hist.iloc[-1]) else 0.0
        macd_bullish = bool(macd_val > macd_sig)

        # Göreceli Hacim (RVOL)
        rvol = round(df['Volume'].iloc[-1] / hacim_ort, 2) if hacim_ort > 0 else 1.0
        hacim_yuksek = bool(rvol >= 1.5)

        # Sıkışma içi üçgen yapısı
        ucgen_tip = ucgen_tipi_belirle(df, 20)

        # Yön Eğilimi Skoru
        yon_puan = 0
        if di_yukselis_baskin: yon_puan += 1
        else: yon_puan -= 1
        if birikim: yon_puan += 1
        if dagitim: yon_puan -= 1
        if ucgen_tip == "yukselen": yon_puan += 1
        elif ucgen_tip == "alcalan": yon_puan -= 1
        if trend_yukselis is True: yon_puan += 1
        elif trend_yukselis is False: yon_puan -= 1

        if yon_puan >= 2:
            yon_bias = "Yukarı"
        elif yon_puan <= -2:
            yon_bias = "Aşağı"
        else:
            yon_bias = "Nötr"

        # Hareket aralığı
        if len(df) >= 30:
            menzil_genislik = df['High'].iloc[-30:].max() - df['Low'].iloc[-30:].min()
        else:
            menzil_genislik = atr_val * 5
        menzil_yukari = son_kapanis + menzil_genislik
        menzil_asagi = max(son_kapanis - menzil_genislik, son_kapanis * 0.5)

        rsi_genel = (45 <= rsi_val <= 70)
        ema_uygun = (son_kapanis > ema21_val)
        rsi_garanti = (45 <= rsi_val <= 65)

        # Patlama potansiyeli tespiti (Bollinger daralma + akıllı para girişi)
        patlama_adayi = bool(sikisma and birikim)

        # Alım Aralığı [Min - Max]
        alim_min = ema21_val * 0.97
        alim_max = ema21_val * 1.01
        
        # Alım Durumu
        fark_yuzde = (son_kapanis - alim_max) / son_kapanis * 100
        if son_kapanis <= alim_max:
            alim_durum = "ŞİMDİ"
        elif fark_yuzde <= 2.5:
            alim_durum = "YAKIN"
        else:
            alim_durum = "BEKLE"

        # Risk analizinde alım fiyatı olarak güncel kapanış fiyatı kullanılır
        risk_buy_price = son_kapanis

        # Stop-Loss: Giriş fiyatının 2.0 * ATR altı (Zararı %3-5 arasında sınırlar)
        stop_val = son_kapanis - (atr_val * 2.0)
        if stop_val <= 0:
            stop_val = son_kapanis * 0.9

        # Kâr Hedefi 1 (Kısmi Satış Hedefi: 1.5 * ATR üzeri)
        kar_hedef_1 = son_kapanis + (atr_val * 1.5)

        # Kâr Hedefi 2 (Ana Kırılım Hedefi: 3.0 * ATR üzeri)
        kar_hedef_2 = son_kapanis + (atr_val * 3.0)

        # Risk/Ödül Oranları (R/O)
        risk = son_kapanis - stop_val
        ro_1 = round((kar_hedef_1 - son_kapanis) / risk, 2) if risk > 0 else 0
        ro_2 = round((kar_hedef_2 - son_kapanis) / risk, 2) if risk > 0 else 0

        # Beklenen Kâr Yüzdeleri
        beklenen_kar_yuzde_1 = round(((kar_hedef_1 - son_kapanis) / son_kapanis) * 100, 2) if son_kapanis > 0 else 0
        beklenen_kar_yuzde_2 = round(((kar_hedef_2 - son_kapanis) / son_kapanis) * 100, 2) if son_kapanis > 0 else 0

        # Gelişmiş Skorlama
        skor = 10
        if rsi_genel: skor += 10
        if ema_uygun: skor += 15
        if trend_yukselis: skor += 20
        if macd_bullish: skor += 15
        if adx_val >= 25: skor += 10
        elif adx_val < 18: skor -= 10
        if rvol >= 1.5: skor += 15
        elif rvol >= 1.0: skor += 5
        if roc10 > 0: skor += 5
        if ro_2 >= 1.5: skor += 10
        if sikisma: skor += 8
        if hacim_kurumus: skor += 4
        if birikim: skor += 8
        if patlama_adayi: skor += 15
        if yon_bias == "Yukarı": skor += 10
        elif yon_bias == "Aşağı": skor -= 15

        # Garanti Koşulları (Backtest Optimizasyonlu Güvenli Filtreler)
        garanti = (
            skor >= 75 and
            ro_2 >= 1.1 and
            rsi_garanti and
            (trend_yukselis is True) and
            macd_bullish and
            (yon_bias != "Aşağı") and
            (adx_val >= 20.0)
        )

        skor_goster = skor + 5 if (garanti and rsi_garanti) else skor
        if ro_2 >= 2.5 and garanti:
            skor_goster += 5

        # Kripto birimini TL'ye çevir
        if piyasa["id"] == "KR":
            son_kapanis = son_kapanis * usd_try
            ema21_val = ema21_val * usd_try
            alim_min = alim_min * usd_try
            alim_max = alim_max * usd_try
            stop_val = stop_val * usd_try
            kar_hedef_1 = kar_hedef_1 * usd_try
            kar_hedef_2 = kar_hedef_2 * usd_try
            menzil_yukari = menzil_yukari * usd_try
            menzil_asagi = menzil_asagi * usd_try

        fiyat_guncel = round(son_kapanis, 2)
        gosterim_adi = ticker.replace(".IS", "").replace("-USD", "TRY")
        birim = "₺" if piyasa["id"] in ["TR", "KR"] else "$"
        tv_link = tv_linki_olustur(gosterim_adi, piyasa["id"])

        if alim_max > stop_val and fiyat_guncel > stop_val:
            return {
                "symbol": gosterim_adi,
                "fiyat": fiyat_guncel,
                "birim": birim,
                "degisim": degisim,
                "rsi": rsi_val,
                "skor": skor_goster,
                "alim_min": round(alim_min, 2),
                "alim_max": round(alim_max, 2),
                "alim_durum": alim_durum,
                "stop": round(stop_val, 2),
                "kar_hedef_1": round(kar_hedef_1, 2),
                "kar_hedef_2": round(kar_hedef_2, 2),
                "ro_1": ro_1,
                "ro_2": ro_2,
                "beklenen_kar_yuzde_1": beklenen_kar_yuzde_1,
                "beklenen_kar_yuzde_2": beklenen_kar_yuzde_2,
                "trend_yukselis": trend_yukselis,
                "sikisma": sikisma,
                "hacim_kurumus": hacim_kurumus,
                "birikim": birikim,
                "birikim_raw": birikim,
                "dagitim": dagitim,
                "yon_bias": yon_bias,
                "ucgen_tip": ucgen_tip,
                "menzil_yukari": round(menzil_yukari, 2),
                "menzil_asagi": round(menzil_asagi, 2),
                "roc10": roc10,
                "garanti": garanti,
                "acik_mi": acik_mi,
                "hacim_yuksek": hacim_yuksek,
                "piyasa_id": piyasa["id"],
                "tv_link": tv_link,
                "patlama_adayi": patlama_adayi,
                "adx": adx_val,
                "macd_bullish": macd_bullish,
                "macd_val": macd_val,
                "macd_sig": macd_sig,
                "macd_hist": macd_hist_val,
                "rvol": rvol
            }
    except Exception as e:
        if VERBOSE:
            print(f"Hata ({ticker}): {str(e)[:50]}")
    return None

# --- JSON SERIALIZATION HELPER FOR NUMPY ---
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, np.bool_):
                return bool(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return super(NumpyEncoder, self).default(obj)

# --- HTML/CSS DASHBOARD ÜRETİCİSİ ---
def html_dashboard_olustur(gosterilecek_liste, tum_sonuclar, usd_try, eur_try):
    try:
        yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), DASHBOARD_DOSYASI)
        guncelleme_zamani = datetime.now(ISTANBUL_TZ).strftime("%d.%m.%Y %H:%M:%S")

        # Javascript verisini JSON'a çevir
        json_data = json.dumps(tum_sonuclar, cls=NumpyEncoder, ensure_ascii=False)

        html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Borsa ve Kripto Tarama Gösterge Paneli</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-main: #0b0f19;
            --bg-card: rgba(17, 24, 39, 0.75);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --primary: #10b981;
            --primary-glow: rgba(16, 185, 129, 0.2);
            --danger: #ef4444;
            --warning: #f59e0b;
            --info: #3b82f6;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-main);
            color: var(--text-main);
            padding: 2rem;
            min-height: 100vh;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(16, 185, 129, 0.04) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(59, 130, 246, 0.04) 0%, transparent 40%);
            background-attachment: fixed;
        }}

        .container {{
            max-width: 1500px;
            margin: 0 auto;
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
            flex-wrap: wrap;
            gap: 1rem;
        }}

        .logo-area {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .logo-icon {{
            background: linear-gradient(135deg, var(--primary), var(--info));
            width: 44px;
            height: 44px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 1.3rem;
            box-shadow: 0 4px 10px rgba(16, 185, 129, 0.3);
        }}

        .logo-title h1 {{
            font-size: 1.4rem;
            font-weight: 700;
            letter-spacing: -0.025em;
        }}

        .logo-title p {{
            font-size: 0.8rem;
            color: var(--text-muted);
        }}

        .stats-bar {{
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
        }}

        .stat-item {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            backdrop-filter: blur(8px);
        }}

        .stat-val {{
            font-weight: 600;
            color: #fff;
        }}

        .live-dot {{
            width: 8px;
            height: 8px;
            background-color: var(--primary);
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 8px var(--primary);
            animation: pulse 1.5s infinite;
        }}

        @keyframes pulse {{
            0% {{ opacity: 0.5; }}
            50% {{ opacity: 1; }}
            100% {{ opacity: 0.5; }}
        }}

        /* Summary Cards Grid */
        .cards-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            backdrop-filter: blur(8px);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s, border-color 0.2s;
        }}

        .card:hover {{
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.12);
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
            color: var(--text-muted);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .card-value {{
            font-size: 1.8rem;
            font-weight: 700;
            color: #fff;
            margin-bottom: 0.25rem;
        }}

        .card-desc {{
            font-size: 0.8rem;
            color: var(--text-muted);
        }}

        /* Controls Section */
        .controls {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            gap: 1rem;
            flex-wrap: wrap;
        }}

        .tabs {{
            display: flex;
            background: var(--bg-card);
            padding: 4px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}

        .tab-btn {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 0.5rem 1.25rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 500;
            transition: all 0.2s;
        }}

        .tab-btn.active {{
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
        }}

        .search-container {{
            position: relative;
            flex-grow: 1;
            max-width: 320px;
        }}

        .search-input {{
            width: 100%;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 0.55rem 1rem 0.55rem 2.2rem;
            border-radius: 8px;
            color: var(--text-main);
            font-size: 0.85rem;
            outline: none;
            transition: border-color 0.2s;
        }}

        .search-input:focus {{
            border-color: var(--primary);
        }}

        .search-icon {{
            position: absolute;
            left: 0.8rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            pointer-events: none;
        }}

        .quick-filters {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}

        .filter-chip {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 0.4rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 0.35rem;
            color: var(--text-muted);
        }}

        .filter-chip:hover {{
            border-color: rgba(255, 255, 255, 0.15);
            color: var(--text-main);
        }}

        .filter-chip.active {{
            background: rgba(16, 185, 129, 0.12);
            border-color: var(--primary);
            color: var(--primary);
        }}

        /* Table Design */
        .table-container {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow-x: auto;
            backdrop-filter: blur(8px);
            margin-bottom: 2rem;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.85rem;
        }}

        th {{
            background: rgba(10, 15, 30, 0.5);
            font-weight: 600;
            color: var(--text-muted);
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
            cursor: pointer;
            user-select: none;
            transition: color 0.2s;
        }}

        th:hover {{
            color: #fff;
        }}

        td {{
            padding: 0.9rem 1rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }}

        tr:last-child td {{
            border-bottom: none;
        }}

        tr:hover td {{
            background: rgba(255, 255, 255, 0.015);
        }}

        /* Badge Designs */
        .badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.25rem 0.5rem;
            border-radius: 6px;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.02em;
        }}

        .badge-now {{ background: rgba(16, 185, 129, 0.12); color: var(--primary); }}
        .badge-near {{ background: rgba(245, 158, 11, 0.12); color: var(--warning); }}
        .badge-wait {{ background: rgba(239, 68, 68, 0.12); color: var(--danger); }}
        .badge-izl {{ background: rgba(59, 130, 246, 0.12); color: var(--info); }}
        .badge-garanti {{
            background: linear-gradient(135deg, var(--primary), var(--info));
            color: #fff;
            box-shadow: 0 2px 5px rgba(0,0,0,0.15);
        }}

        .market-dot {{
            width: 7px;
            height: 7px;
            border-radius: 50%;
            display: inline-block;
        }}
        .market-open {{
            background-color: var(--primary);
            box-shadow: 0 0 6px var(--primary);
        }}
        .market-closed {{
            background-color: var(--danger);
        }}

        .text-green {{ color: var(--primary) !important; }}
        .text-red {{ color: var(--danger) !important; }}
        .text-yellow {{ color: var(--warning) !important; }}
        .text-muted {{ color: var(--text-muted) !important; }}

        .symbol-cell {{
            display: flex;
            align-items: center;
            gap: 0.35rem;
            font-weight: 600;
            color: #fff;
        }}

        .icon-badges {{
            display: flex;
            gap: 2px;
        }}

        .icon-badge {{
            font-size: 0.8rem;
        }}

        .btn-tv {{
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 0.3rem 0.6rem;
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.75rem;
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            transition: all 0.2s;
        }}

        .btn-tv:hover {{
            background: #fff;
            color: #000;
            border-color: #fff;
        }}

        .no-data {{
            text-align: center;
            padding: 4rem;
            color: var(--text-muted);
            font-size: 0.95rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-area">
                <div class="logo-icon">AG</div>
                <div class="logo-title">
                    <h1>Borsa &amp; Kripto Tarama Paneli</h1>
                    <p>Antigravity Engine v7 • Canlı Tarama Verileri</p>
                </div>
            </div>
            <div class="stats-bar">
                <div class="stat-item">
                    <span class="live-dot"></span>
                    <span>Son Güncelleme:</span>
                    <span class="stat-val" id="last-update">{guncelleme_zamani}</span>
                </div>
                <div class="stat-item">
                    <span>Dolar:</span>
                    <span class="stat-val">₺{usd_try:.2f}</span>
                </div>
                <div class="stat-item">
                    <span>Euro:</span>
                    <span class="stat-val">₺{eur_try:.2f}</span>
                </div>
            </div>
        </header>

        <!-- Summary Cards -->
        <div class="cards-grid">
            <div class="card">
                <div class="card-header">
                    <span>Toplam Taranan</span>
                    <span style="font-size:1.1rem">🔍</span>
                </div>
                <div class="card-value" id="card-total">0</div>
                <div class="card-desc">Aktif sembol listesi büyüklüğü</div>
            </div>
            <div class="card">
                <div class="card-header">
                    <span>Garanti Sinyaller</span>
                    <span style="font-size:1.1rem">🛡️</span>
                </div>
                <div class="card-value text-green" id="card-guaranteed">0</div>
                <div class="card-desc">RSI, Trend ve Yön uyumlu AL sinyalleri</div>
            </div>
            <div class="card">
                <div class="card-header">
                    <span>Patlama Adayları</span>
                    <span style="font-size:1.1rem">🚀</span>
                </div>
                <div class="card-value" id="card-breakouts" style="color: #3b82f6 !important;">0</div>
                <div class="card-desc">Sıkışma + Birikim (Yüksek Kâr Adayı)</div>
            </div>
            <div class="card">
                <div class="card-header">
                    <span>Sıkışan (Squeeze)</span>
                    <span style="font-size:1.1rem">🌀</span>
                </div>
                <div class="card-value text-yellow" id="card-squeeze">0</div>
                <div class="card-desc">Bollinger squeeze durumundaki semboller</div>
            </div>
            <div class="card">
                <div class="card-header">
                    <span>Para Akışı Birikim</span>
                    <span style="font-size:1.1rem">📥</span>
                </div>
                <div class="card-value text-blue" id="card-accumulation">0</div>
                <div class="card-desc">Fiyat sabitken hacmi artan (OBV)</div>
            </div>
        </div>

        <!-- Filters & Search -->
        <div class="controls">
            <div class="tabs">
                <button class="tab-btn active" onclick="setTab('ALL')">Tümü</button>
                <button class="tab-btn" onclick="setTab('TR')">BIST</button>
                <button class="tab-btn" onclick="setTab('US')">ABD Borsası</button>
                <button class="tab-btn" onclick="setTab('KR')">Kripto</button>
            </div>
            
            <div class="quick-filters">
                <button class="filter-chip" id="chip-guaranteed" onclick="toggleFilter('guaranteed')">
                    🛡️ Sadece Garanti
                </button>
                <button class="filter-chip" id="chip-breakout" onclick="toggleFilter('breakout')">
                    🚀 Patlama Adayı
                </button>
                <button class="filter-chip" id="chip-squeeze" onclick="toggleFilter('squeeze')">
                    🌀 Sıkışma
                </button>
                <button class="filter-chip" id="chip-accumulation" onclick="toggleFilter('accumulation')">
                    📥 OBV Birikim
                </button>
                <button class="filter-chip" id="chip-now" onclick="toggleFilter('now')">
                    🟢 Alım: ŞİMDİ
                </button>
            </div>

            <div class="search-container">
                <span class="search-icon">🔍</span>
                <input type="text" class="search-input" id="search-input" placeholder="Sembol ara..." oninput="handleSearch(this.value)">
            </div>
        </div>

        <!-- Table -->
        <div class="table-container">
            <table id="results-table">
                <thead>
                    <tr>
                        <th>P</th>
                        <th onclick="handleSort('symbol')">Sembol</th>
                        <th onclick="handleSort('fiyat')">Fiyat</th>
                        <th onclick="handleSort('degisim')">Değişim</th>
                        <th onclick="handleSort('rsi')">RSI</th>
                        <th onclick="handleSort('trend_yukselis')">Trend</th>
                        <th onclick="handleSort('macd_bullish')">MACD</th>
                        <th onclick="handleSort('adx')">ADX (Güç)</th>
                        <th onclick="handleSort('yon_bias')">Yön</th>
                        <th onclick="handleSort('alim_max')">Alım Aralığı</th>
                        <th onclick="handleSort('stop')">Stop-Loss</th>
                        <th onclick="handleSort('kar_hedef_1')">Hedef 1 (Kısmi)</th>
                        <th onclick="handleSort('kar_hedef_2')">Hedef 2 (Patlama)</th>
                        <th onclick="handleSort('ro_2')">R/O Oranı</th>
                        <th onclick="handleSort('beklenen_kar_yuzde_2')">Beklenen Kâr</th>
                        <th onclick="handleSort('menzil_yukari')">Olası Aralık</th>
                        <th onclick="handleSort('skor')">Skor</th>
                        <th>Durum</th>
                        <th>Grafik</th>
                    </tr>
                </thead>
                <tbody id="table-body">
                    <!-- Javascript ile doldurulacak -->
                </tbody>
            </table>
            <div id="no-data-msg" class="no-data" style="display:none;">
                Aranan kriterlere uygun veri bulunamadı.
            </div>
        </div>
    </div>

    <script>
        // Python tarafından enjekte edilen veri
        const dataset = {json_data};

        let currentTab = 'ALL';
        let searchQuery = '';
        let filterGuaranteed = false;
        let filterBreakout = false;
        let filterSqueeze = false;
        let filterAccumulation = false;
        let filterNow = false;
        
        let sortColumn = 'garanti'; // default
        let sortDirection = 'desc';

        // Başlangıç istatistikleri ve render
        function initDashboard() {{
            updateCards();
            renderTable();
        }}

        function updateCards() {{
            document.getElementById('card-total').innerText = dataset.length;
            document.getElementById('card-guaranteed').innerText = dataset.filter(x => x.garanti).length;
            document.getElementById('card-breakouts').innerText = dataset.filter(x => x.patlama_adayi).length;
            document.getElementById('card-squeeze').innerText = dataset.filter(x => x.sikisma).length;
            document.getElementById('card-accumulation').innerText = dataset.filter(x => x.birikim_raw).length;
        }}

        function setTab(tab) {{
            currentTab = tab;
            // Tab active class güncelle
            const buttons = document.querySelectorAll('.tab-btn');
            buttons.forEach(btn => {{
                if (btn.innerText === 'Tümü' && tab === 'ALL') btn.classList.add('active');
                else if (btn.innerText === 'BIST' && tab === 'TR') btn.classList.add('active');
                else if (btn.innerText === 'ABD Borsası' && tab === 'US') btn.classList.add('active');
                else if (btn.innerText === 'Kripto' && tab === 'KR') btn.classList.add('active');
                else btn.classList.remove('active');
            }});
            renderTable();
        }}

        function toggleFilter(filter) {{
            if (filter === 'guaranteed') {{
                filterGuaranteed = !filterGuaranteed;
                document.getElementById('chip-guaranteed').classList.toggle('active', filterGuaranteed);
            }} else if (filter === 'squeeze') {{
                filterSqueeze = !filterSqueeze;
                document.getElementById('chip-squeeze').classList.toggle('active', filterSqueeze);
            }} else if (filter === 'accumulation') {{
                filterAccumulation = !filterAccumulation;
                document.getElementById('chip-accumulation').classList.toggle('active', filterAccumulation);
            }} else if (filter === 'now') {{
                filterNow = !filterNow;
                document.getElementById('chip-now').classList.toggle('active', filterNow);
            }} else if (filter === 'breakout') {{
                filterBreakout = !filterBreakout;
                document.getElementById('chip-breakout').classList.toggle('active', filterBreakout);
            }}
            renderTable();
        }}

        function handleSearch(val) {{
            searchQuery = val.toLowerCase().trim();
            renderTable();
        }}

        function handleSort(column) {{
            if (sortColumn === column) {{
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
            }} else {{
                sortColumn = column;
                sortDirection = 'desc';
            }}
            
            // Header işaretçilerini güncelle
            const headers = document.querySelectorAll('th');
            headers.forEach(th => {{
                th.classList.remove('sort-asc', 'sort-desc');
                if (th.getAttribute('onclick') && th.getAttribute('onclick').includes(column)) {{
                    th.classList.add(sortDirection === 'asc' ? 'sort-asc' : 'sort-desc');
                }}
            }});
            
            renderTable();
        }}

        function formatCurrency(val, birim) {{
            if (val >= 1000000) return (val/1000000).toFixed(1) + 'M' + birim;
            if (val >= 1000) return val.toFixed(0) + birim;
            return val.toFixed(1) + birim;
        }}

        function renderTable() {{
            const tbody = document.getElementById('table-body');
            const noDataMsg = document.getElementById('no-data-msg');
            
            // Filtreleme
            let filtered = dataset.filter(item => {{
                // Tab filtresi
                if (currentTab !== 'ALL' && item.piyasa_id !== currentTab) return false;
                
                // Arama filtresi
                if (searchQuery && !item.symbol.toLowerCase().includes(searchQuery)) return false;
                
                // Chip filtreleri
                if (filterGuaranteed && !item.garanti) return false;
                if (filterBreakout && !item.patlama_adayi) return false;
                if (filterSqueeze && !item.sikisma) return false;
                if (filterAccumulation && !item.birikim_raw) return false;
                if (filterNow && item.alim_durum !== 'ŞİMDİ') return false;
                
                return true;
            }});

            // Sıralama
            filtered.sort((a, b) => {{
                let valA = a[sortColumn];
                let valB = b[sortColumn];

                // null veya undefined durumları
                if (valA === null || valA === undefined) valA = sortDirection === 'asc' ? Infinity : -Infinity;
                if (valB === null || valB === undefined) valB = sortDirection === 'asc' ? Infinity : -Infinity;

                // String karşılaştırması
                if (typeof valA === 'string') {{
                    return sortDirection === 'asc' 
                        ? valA.localeCompare(valB) 
                        : valB.localeCompare(valA);
                }}

                // Boolean karşılaştırması
                if (typeof valA === 'boolean') {{
                    valA = valA ? 1 : 0;
                    valB = valB ? 1 : 0;
                }}

                return sortDirection === 'asc' ? valA - valB : valB - valA;
            }});

            if (filtered.length === 0) {{
                tbody.innerHTML = '';
                noDataMsg.style.display = 'block';
                return;
            }}
            
            noDataMsg.style.display = 'none';
            
            let html = '';
            filtered.forEach(item => {{
                const pDot = item.acik_mi 
                    ? '<span class="market-dot market-open" title="Açık"></span>' 
                    : '<span class="market-dot market-closed" title="Kapalı"></span>';
                
                const degisimRenk = item.degisim > 0 ? 'text-green' : (item.degisim < 0 ? 'text-red' : '');
                const degisimSign = item.degisim > 0 ? '+' : '';
                
                let rsiRenk = 'text-green';
                if (item.rsi >= 70) rsiRenk = 'text-red';
                else if (item.rsi >= 60) rsiRenk = 'text-yellow';
                else if (item.rsi < 30) rsiRenk = 'text-blue';

                const trendStr = item.trend_yukselis === true 
                    ? '<span class="text-green" style="font-weight:bold;">↑</span>' 
                    : (item.trend_yukselis === false ? '<span class="text-red">↓</span>' : '<span class="text-muted">?</span>');

                const macdStr = item.macd_bullish 
                    ? '<span class="text-green" style="font-weight:600;">AL</span>' 
                    : '<span class="text-red" style="font-weight:600;">SAT</span>';

                let adxRenk = 'text-muted';
                if (item.adx >= 25) adxRenk = 'text-green';
                else if (item.adx < 18) adxRenk = 'text-muted';
                else adxRenk = 'text-main';
                const adxStr = `<span class="${{adxRenk}}" style="font-weight:600;">${{item.adx.toFixed(0)}}</span>`;

                let yonRenk = '';
                let yonIcon = '–';
                if (item.yon_bias === 'Yukarı') {{ yonRenk = 'text-green'; yonIcon = '▲'; }}
                else if (item.yon_bias === 'Aşağı') {{ yonRenk = 'text-red'; yonIcon = '▼'; }}

                let alimRenk = 'text-muted';
                if (item.alim_durum === 'ŞİMDİ') alimRenk = 'text-green';
                else if (item.alim_durum === 'YAKIN') alimRenk = 'text-yellow';
                else if (item.alim_durum === 'BEKLE') alimRenk = 'text-red';

                let roRenk = 'text-red';
                if (item.ro_2 >= 2.0) roRenk = 'text-green';
                else if (item.ro_2 >= 1.5) roRenk = 'text-green';

                let karRenk = 'text-muted';
                if (item.beklenen_kar_yuzde_2 >= 8) karRenk = 'text-green';
                else if (item.beklenen_kar_yuzde_2 >= 4) karRenk = 'text-yellow';

                let durumBadge = '';
                if (item.garanti) {{
                    durumBadge = '<span class="badge badge-garanti">🛡️ Garanti</span>';
                }} else {{
                    if (item.skor >= 90) durumBadge = '<span class="badge badge-izl">İzle</span>';
                    else if (item.skor >= 70) durumBadge = '<span class="badge badge-near">Potansiyel</span>';
                    else durumBadge = '<span class="badge badge-wait">Bekle</span>';
                }}

                let icons = '';
                if (item.hacim_yuksek) icons += '<span class="icon-badge" title="Yüksek Hacim">🔥</span>';
                if (item.sikisma) icons += '<span class="icon-badge" title="Bant Sıkışması (Breakout Yakın)">🌀</span>';
                if (item.birikim_raw) icons += '<span class="icon-badge" title="OBV Birikim (Akıllı Para Girişi)">📥</span>';
                if (item.patlama_adayi) icons += '<span class="icon-badge" title="PATLAMA POTANSİYELİ! 🚀">🚀</span>';

                let alimAraligiStr = formatCurrency(item.alim_min, item.birim) + ' - ' + formatCurrency(item.alim_max, item.birim);

                html += `
                    <tr>
                        <td style="text-align:center;">${{pDot}}</td>
                        <td>
                            <div class="symbol-cell">
                                <span>${{item.symbol}}</span>
                                <div class="icon-badges">${{icons}}</div>
                            </div>
                        </td>
                        <td><strong style="color:#fff;">${{formatCurrency(item.fiyat, item.birim)}}</strong></td>
                        <td class="${{degisimRenk}}">${{degisimSign}}${{item.degisim.toFixed(1)}}%</td>
                        <td class="${{rsiRenk}}" style="font-weight:600; text-align:center;">${{item.rsi.toFixed(0)}}</td>
                        <td style="text-align:center;">${{trendStr}}</td>
                        <td style="text-align:center;">${{macdStr}}</td>
                        <td style="text-align:center;">${{adxStr}}</td>
                        <td class="${{yonRenk}}" style="text-align:center; font-weight:bold;">${{yonIcon}}</td>
                        <td class="${{alimRenk}}" style="font-weight:600;">${{alimAraligiStr}}</td>
                        <td class="text-red">${{formatCurrency(item.stop, item.birim)}}</td>
                        <td class="text-green">${{formatCurrency(item.kar_hedef_1, item.birim)}}</td>
                        <td class="text-green" style="font-weight:600;">${{formatCurrency(item.kar_hedef_2, item.birim)}}</td>
                        <td class="${{roRenk}}" style="text-align:center; font-weight:600;">${{item.ro_1}} / ${{item.ro_2}}</td>
                        <td class="${{karRenk}}">+${{item.beklenen_kar_yuzde_1.toFixed(0)}}% / +${{item.beklenen_kar_yuzde_2.toFixed(0)}}%</td>
                        <td class="text-muted" style="font-size:0.8rem;">
                            ${{formatCurrency(item.menzil_asagi, item.birim)}}-${{formatCurrency(item.menzil_yukari, item.birim)}}
                        </td>
                        <td style="text-align:center;"><strong>${{item.skor}}</strong></td>
                        <td>${{durumBadge}}</td>
                        <td>
                            <a href="${{item.tv_link}}" target="_blank" class="btn-tv">
                                Grafik ↗
                            </a>
                        </td>
                    </tr>
                `;
            }});
            
            tbody.innerHTML = html;
        }}

        // Sayfa yüklendiğinde başlat
        window.onload = initDashboard;
    </script>
</body>
</html>
"""
        with open(yol, "w", encoding="utf-8") as f:
            f.write(html_content)
        if VERBOSE:
            print(f"Web Gösterge Paneli güncellendi: {yol}")
    except Exception as e:
        print(f"HTML Dashboard oluşturma hatası: {e}")

# --- ANA TARAMA DÖNGÜSÜ ---
def piyasa_tara():
    try:
        os.system('cls' if os.name == 'nt' else 'clear')

        usd_try = guncel_dolar_kuru_al()
        eur_try = guncel_euro_kuru_al()
        bugun_str = datetime.now(ISTANBUL_TZ).strftime("%Y%m%d")

        # Eşzamanlı tarama için tüm sembolleri listeye ekle
        tarama_listesi = []
        for piyasa in PIYASALAR:
            acik_mi = piyasa_acik_mi(piyasa["id"])
            for ticker in piyasa["semboller"]:
                tarama_listesi.append((ticker, piyasa, acik_mi))

        piyasa_sonuclari = {p["id"]: [] for p in PIYASALAR}
        tum_sinyaller_listesi = []
        toplam_taranan = len(tarama_listesi)

        print(Fore.CYAN + f"[*] {toplam_taranan} sembol paralel olarak taranıyor (max 10 iş parçacığı)..." + Style.RESET_ALL)

        # ThreadPool ile eşzamanlı veri çekme
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ticker = {
                executor.submit(sembol_tara, item[0], item[1], usd_try, item[2]): item[0] 
                for item in tarama_listesi
            }
            
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    res = future.result()
                    if res is not None:
                        piyasa_sonuclari[res["piyasa_id"]].append(res)
                        tum_sinyaller_listesi.append(res)
                except Exception as e:
                    if VERBOSE:
                        print(f"İşlem hatası ({ticker}): {e}")

        # Toplam kritere uyan (stop limitinin üstünde kalıp analiz listesine girenler)
        toplam_kritere_uyan = sum(len(piyasa_sonuclari[p["id"]]) for p in PIYASALAR)

        # Her piyasadan en iyi 5 sembolü seçip konsolda göstereceğiz
        gosterilecek_konsol = []
        for piyasa in PIYASALAR:
            liste = piyasa_sonuclari[piyasa["id"]]
            # Sıralama: Garanti durumuna, skora ve beklenen kâr yüzdesine göre
            liste.sort(key=lambda x: (x["garanti"], x["skor"], x["beklenen_kar_yuzde_2"]), reverse=True)
            secilen = liste[:5]
            gosterilecek_konsol.extend(secilen)

        # Konsol listesini de kendi içinde sırala
        gosterilecek_konsol.sort(key=lambda x: (x["garanti"], x["skor"], x["beklenen_kar_yuzde_2"]), reverse=True)

        # === PRETTYTABLE OLUŞTUR ===
        tablo = PrettyTable()
        tablo.field_names = [
            "P", "Sembol", "Fyt", "%", "RSI", "T", "M", "A",
            "Alım", "Stop", "Hedef", "R/O", "Kâr%", "S", "Drm"
        ]

        # Hizalamalar
        for col in ["P", "RSI", "T", "M", "A", "R/O", "S", "Drm"]:
            tablo.align[col] = "c"
        tablo.align["Sembol"] = "l"
        for col in ["Fyt", "%", "Alım", "Stop", "Hedef", "Kâr%"]:
            tablo.align[col] = "r"

        garanti_sayisi = 0
        for item in gosterilecek_konsol:
            try:
                if item["degisim"] > 0:
                    degisim_str = f"+{item['degisim']:.1f}%"
                    degisim_renk = Fore.GREEN
                elif item["degisim"] < 0:
                    degisim_str = f"{item['degisim']:.1f}%"
                    degisim_renk = Fore.RED
                else:
                    degisim_str = f"{item['degisim']:.1f}%"
                    degisim_renk = Fore.WHITE

                if item["rsi"] >= 70:
                    rsi_r = Fore.RED + Style.BRIGHT
                elif item["rsi"] >= 60:
                    rsi_r = Fore.YELLOW + Style.BRIGHT
                elif item["rsi"] >= 50:
                    rsi_r = Fore.GREEN + Style.BRIGHT
                elif item["rsi"] >= 30:
                    rsi_r = Fore.CYAN
                else:
                    rsi_r = Fore.BLUE + Style.BRIGHT

                if item["garanti"]:
                    skor_str = Fore.GREEN + Style.BRIGHT + str(item["skor"]) + Style.RESET_ALL
                    ro_str = f"{item['ro_2']}"
                    ro_str = (Fore.GREEN + Style.BRIGHT if item["ro_2"] >= 2.0 else Fore.GREEN) + ro_str + Style.RESET_ALL
                    
                    if item["acik_mi"]:
                        durum_str = Back.GREEN + Fore.BLACK + Style.BRIGHT + " AL " + Style.RESET_ALL
                    else:
                        durum_str = Back.YELLOW + Fore.BLACK + Style.BRIGHT + "AL*" + Style.RESET_ALL
                    garanti_sayisi += 1
                else:
                    if item["skor"] >= 90:
                        skor_str = Fore.YELLOW + Style.BRIGHT + str(item["skor"]) + Style.RESET_ALL
                    elif item["skor"] >= 70:
                        skor_str = Fore.YELLOW + str(item["skor"]) + Style.RESET_ALL
                    else:
                        skor_str = Fore.WHITE + str(item["skor"]) + Style.RESET_ALL

                    ro_str = f"{item['ro_2']}"
                    if item["ro_2"] >= 2.0:
                        ro_str = Fore.CYAN + ro_str + Style.RESET_ALL
                    elif item["ro_2"] >= 1.5:
                        ro_str = Fore.WHITE + ro_str + Style.RESET_ALL
                    else:
                        ro_str = Fore.RED + ro_str + Style.RESET_ALL

                    if item["skor"] >= 90:
                        durum_str = Fore.CYAN + "İzl" + Style.RESET_ALL
                    elif item["skor"] >= 70:
                        durum_str = Fore.WHITE + "Pot" + Style.RESET_ALL
                    else:
                        durum_str = Fore.RED + "Bek" + Style.RESET_ALL

                piyasa_gosterge = "●" if item["acik_mi"] else "○"
                piyasa_renk = Fore.GREEN if item["acik_mi"] else Fore.RED

                alim_renk = Fore.GREEN + Style.BRIGHT if item["alim_durum"] == "ŞİMDİ" else (Fore.YELLOW if item["alim_durum"] == "YAKIN" else Fore.RED)

                hacim = " 🔥" if item["hacim_yuksek"] else ""
                erken_ikon = ""
                if item.get("sikisma"): erken_ikon += " 🌀"
                if item.get("birikim_raw"): erken_ikon += " 📥"
                if item.get("patlama_adayi"): erken_ikon += " 🚀"  # Patlama adayı roketi

                if item["trend_yukselis"] is True:
                    trend_str = Fore.GREEN + Style.BRIGHT + "↑" + Style.RESET_ALL
                elif item["trend_yukselis"] is False:
                    trend_str = Fore.RED + "↓" + Style.RESET_ALL
                else:
                    trend_str = Fore.LIGHTBLACK_EX + "?" + Style.RESET_ALL

                # MACD
                if item["macd_bullish"]:
                    macd_str = Fore.GREEN + "AL" + Style.RESET_ALL
                else:
                    macd_str = Fore.RED + "SAT" + Style.RESET_ALL

                # ADX
                adx_v = item["adx"]
                if adx_v >= 25:
                    adx_str = Fore.GREEN + Style.BRIGHT + f"{adx_v:.0f}" + Style.RESET_ALL
                elif adx_v < 18:
                    adx_str = Fore.LIGHTBLACK_EX + f"{adx_v:.0f}" + Style.RESET_ALL
                else:
                    adx_str = Fore.WHITE + f"{adx_v:.0f}" + Style.RESET_ALL

                bkl_kar = item["beklenen_kar_yuzde_2"]
                bkl_kar_str = (Fore.GREEN + Style.BRIGHT if bkl_kar >= 8 else (Fore.YELLOW if bkl_kar >= 4 else Fore.WHITE)) + f"+{bkl_kar:.0f}%" + Style.RESET_ALL

                tablo.add_row([
                    f"{piyasa_renk}{piyasa_gosterge}{Style.RESET_ALL}",
                    f"{Fore.CYAN}{Style.BRIGHT}{item['symbol']:<7}{Style.RESET_ALL}{hacim}{erken_ikon}",
                    f"{Fore.WHITE}{deger_formatla(item['fiyat'])}{item['birim']}{Style.RESET_ALL}",
                    f"{degisim_renk}{degisim_str}{Style.RESET_ALL}",
                    f"{rsi_r}{item['rsi']:.0f}{Style.RESET_ALL}",
                    trend_str,
                    macd_str,
                    adx_str,
                    f"{alim_renk}{deger_formatla(item['alim_max'])}{Style.RESET_ALL}",
                    f"{Fore.RED}{deger_formatla(item['stop'])}{Style.RESET_ALL}",
                    f"{Fore.GREEN}{deger_formatla(item['kar_hedef_2'])}{Style.RESET_ALL}",
                    ro_str,
                    bkl_kar_str,
                    skor_str,
                    durum_str
                ])

                # --- Telegram Bildirim Mekanizması ---
                if item["garanti"]:
                    sinyal_key = f"{item['piyasa_id']}_{item['symbol']}_{bugun_str}"
                    if sinyal_key not in gonderilen_sinyaller:
                        try:
                            erken_liste = []
                            if item.get("sikisma"): erken_liste.append("Sıkışma(🌀)")
                            if item.get("hacim_kurumus"): erken_liste.append("Hacim kuruması")
                            if item.get("birikim_raw"): erken_liste.append("OBV birikim(📥)")
                            if item.get("patlama_adayi"): erken_liste.append("Patlama Potansiyeli(🚀)")
                            erken_metin = ", ".join(erken_liste) if erken_liste else "Yok"

                            piyasa_durum_metni = "⚠️ <b>(Piyasa Kapalı - Hafta Sonu Sinyali)</b>\n" if not item["acik_mi"] else ""

                            mesaj = (
                                f"🛡️ <b>{item['symbol']} - GARANTİ AL SİNYALİ</b>\n"
                                f"{piyasa_durum_metni}"
                                f"🌍 <b>Piyasa:</b> {item['piyasa_id']}\n"
                                f"💰 {deger_formatla(item['fiyat'])}{item['birim']} | RSI:{item['rsi']:.0f} | Skor:{item['skor']}\n"
                                f"📈 Trend: {'Yükseliş' if item['trend_yukselis'] else 'Belirsiz'} | Yön: {item['yon_bias']}\n"
                                f"🔎 Erken Sinyaller: {erken_metin}\n"
                                f"📌 Alım Aralığı: {deger_formatla(item['alim_min'])} - {deger_formatla(item['alim_max'])} ({item['alim_durum']})\n"
                                f"🛑 Stop: {deger_formatla(item['stop'])} | 🎯 Hedef-1: {deger_formatla(item['kar_hedef_1'])} | 🚀 Hedef-2: {deger_formatla(item['kar_hedef_2'])}\n"
                                f"⚖️ Risk/Ödül: {item['ro_1']} / {item['ro_2']} | 🎯 Beklenen Kâr: +{item['beklenen_kar_yuzde_1']:.0f}% / +{item['beklenen_kar_yuzde_2']:.0f}%\n"
                                f"↕️ Olası Menzil: {deger_formatla(item['menzil_asagi'])} - {deger_formatla(item['menzil_yukari'])}\n"
                                f"⚠️ Yatırım tavsiyesi değildir."
                            )
                            bildirim_gonder(mesaj)
                            gonderilen_sinyaller.add(sinyal_key)
                        except Exception as e:
                            if VERBOSE:
                                print(f"Telegram gönderim hatası: {e}")

            except Exception as e:
                if VERBOSE:
                    print(f"Satır hatası: {e}")

        # Sinyalleri diske kaydet
        sinyalleri_kaydet(gonderilen_sinyaller)

        # HTML Raporunu Üret (Tüm sonuçları gönderiyoruz, böylece panoda filtreleme yapılabilir)
        html_dashboard_olustur(gosterilecek_konsol, tum_sinyaller_listesi, usd_try, eur_try)

        # === EKRAN ÇIKTISI ===
        print(Fore.LIGHTBLUE_EX + Style.BRIGHT +
              f"💵 USD/TRY: {usd_try:.2f}   Euro/TRY: {eur_try:.2f}   ⏰ {datetime.now(ISTANBUL_TZ).strftime('%H:%M:%S')}"
              + Style.RESET_ALL)
        print()

        print(tablo)

        print(f"\n{Back.GREEN + Fore.BLACK + Style.BRIGHT} 🛡️ Garanti: {garanti_sayisi} {Style.RESET_ALL} | "
              f"{Fore.CYAN}📊 Tüm: {len(gosterilecek_konsol)-garanti_sayisi}{Style.RESET_ALL} | "
              f"{Fore.WHITE}Top: {len(gosterilecek_konsol)}{Style.RESET_ALL}")
        
        piyasa_ozet = " + ".join(f"{p['id']}:{len(p['semboller'])}" for p in PIYASALAR)
        print(f"{Fore.LIGHTBLACK_EX}Toplam taranan: {toplam_taranan} sembol ({piyasa_ozet}) | "
              f"Kritere uyan (stop üstü): {toplam_kritere_uyan}{Style.RESET_ALL}")
        
        print(Fore.GREEN + f"[+] Web Gösterge Paneli başarıyla güncellendi: {DASHBOARD_DOSYASI}" + Style.RESET_ALL)

    except Exception as e:
        hata_mesaji = traceback.format_exc()
        hata_kaydet(hata_mesaji)
        print(Fore.RED + f"\n❌ KRİTİK HATA: {e}" + Style.RESET_ALL)
        print(Fore.YELLOW + f"Hata detayları 'hata_log.txt' dosyasına kaydedildi." + Style.RESET_ALL)
        raise

# === ANA PROGRAM BAŞLANGICI ===
print("=" * 50)
print("BORSA TARAMA ROBOTU BAŞLIYOR (Concurrency + Dashboard)")
print("SÜRÜM: v7.5 (paralel tarama & interaktif web paneli)")
print("=" * 50)

try:
    print("İlk tarama yapılıyor...")
    piyasa_tara()

    if not os.getenv("GITHUB_ACTIONS"):
        while True:
            try:
                print(Fore.LIGHTBLUE_EX + f"\n[{datetime.now(ISTANBUL_TZ).strftime('%H:%M:%S')}] Sonraki tarama: {TARAMA_ARALIGI} dakika sonra..." + Style.RESET_ALL)
                print(Fore.YELLOW + "Kapatmak için Ctrl+C basın" + Style.RESET_ALL)
                time.sleep(TARAMA_ARALIGI * 60)
                # Yapılandırmayı ve sembolleri her döngüde yeniden yükle (config.json güncellenmiş olabilir)
                PIYASALAR, VERBOSE, TARAMA_ARALIGI = config_yukle()
                piyasa_tara()
            except KeyboardInterrupt:
                print("\nKullanıcı tarafından durduruldu.")
                break
            except Exception as e:
                hata_kaydet(traceback.format_exc())
                print(Fore.RED + f"\n[!] Döngü hatası: {e}" + Style.RESET_ALL)
                print(Fore.YELLOW + "15 saniye sonra tekrar deneniyor..." + Style.RESET_ALL)
                time.sleep(15)
    else:
        print(Fore.GREEN + "\n[+] GitHub Actions ortamı algılandı. Tarama başarıyla tamamlandı ve sonlandırılıyor." + Style.RESET_ALL)

except KeyboardInterrupt:
    print("\nProgram kapatıldı.")
except Exception as e:
    hata_kaydet(traceback.format_exc())
    print(Fore.RED + f"\n❌ Program durdu: {e}" + Style.RESET_ALL)
    print(Fore.YELLOW + f"Hata:\n{traceback.format_exc()}" + Style.RESET_ALL)
finally:
    print("\n" + "=" * 50)
    print("Kapatmak için Enter tuşuna basın...")
    guvenli_giris_bekle()
