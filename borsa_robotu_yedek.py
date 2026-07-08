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

# --- STOCHASTIC RSI ---
def stoch_rsi_hesapla(series, period=14, stoch_period=14, smooth_k=3, smooth_d=3):
    """Stochastic RSI — RSI'dan daha hassas aşırı alım/satım tespiti"""
    try:
        rsi = rsi_hesapla(series, period)
        rsi_min = rsi.rolling(window=stoch_period).min()
        rsi_max = rsi.rolling(window=stoch_period).max()
        diff = (rsi_max - rsi_min).replace(0, pd.NA)
        stoch = 100 * (rsi - rsi_min) / diff
        k = stoch.rolling(window=smooth_k).mean().fillna(50)
        d = k.rolling(window=smooth_d).mean().fillna(50)
        return k, d
    except Exception:
        idx = series.index
        return pd.Series(50, index=idx), pd.Series(50, index=idx)

# --- YENİ: EMA CROSSOVER (EMA9 EMA21 kısa vadeli) ---
def ema_crossover_hesapla(df):
    """EMA9 son 5 günde EMA21'i yukarı kestiyse True — en güçlü kısa vadeli sinyal"""
    try:
        if len(df) < 25:
            return False, False
        ema9  = df['Close'].ewm(span=9,  adjust=False).mean()
        ema21 = df['Close'].ewm(span=21, adjust=False).mean()
        # Son 5 gün içinde EMA9, EMA21'i yukarı kesti mi?
        crossover_yukari = False
        crossover_asagi  = False
        for i in range(-5, 0):
            if ema9.iloc[i-1] <= ema21.iloc[i-1] and ema9.iloc[i] > ema21.iloc[i]:
                crossover_yukari = True
            if ema9.iloc[i-1] >= ema21.iloc[i-1] and ema9.iloc[i] < ema21.iloc[i]:
                crossover_asagi = True
        return crossover_yukari, crossover_asagi
    except Exception:
        return False, False

# --- YENİ: HACİM GÜÇ ORANI ---
def hacim_guc_orani_hesapla(df, pencere=10):
    """Son N günde yükselen günlerin hacmini düşen günlerin hacmiyle karşılaştır.
       Oran > 1.3 = boğa baskısı (alım sinyali güçlü)"""
    try:
        if len(df) < pencere + 1:
            return 1.0
        son = df.iloc[-pencere:]
        yukari_gunler = son[son['Close'] > son['Close'].shift(1)]
        asagi_gunler  = son[son['Close'] < son['Close'].shift(1)]
        yukari_hacim  = yukari_gunler['Volume'].sum()
        asagi_hacim   = asagi_gunler['Volume'].sum()
        if asagi_hacim == 0:
            return 2.0
        return round(yukari_hacim / asagi_hacim, 2)
    except Exception:
        return 1.0

# --- YENİ: RSI UYUMSUZLUĞU (BULLISH DIVERGENCE) ---
def rsi_uyumsuzlugu_hesapla(df, pencere=20):
    """Fiyat yeni dip yaparken RSI daha yüksek dip yapıyor = gizli boğa sinyali"""
    try:
        if len(df) < pencere * 2:
            return False
        rsi = rsi_hesapla(df['Close'], 14)
        # Son pencere ve bir önceki penceredeki en düşükleri karşılaştır
        son_fiyat_min   = df['Close'].iloc[-pencere:].min()
        onceki_fiyat_min = df['Close'].iloc[-pencere*2:-pencere].min()
        son_rsi_min     = rsi.iloc[-pencere:].min()
        onceki_rsi_min  = rsi.iloc[-pencere*2:-pencere].min()
        # Fiyat daha düşük dip, RSI daha yüksek dip → bullish divergence
        bullish_div = (son_fiyat_min < onceki_fiyat_min * 0.99) and (son_rsi_min > onceki_rsi_min + 2)
        return bool(bullish_div)
    except Exception:
        return False

# --- YENİ: GEÇ ALIM RİSKİ FİLTRESİ ---
def gec_alim_riski_hesapla(df):
    """52h zirvesine çok yakın VEYA son 10 günde %20+ yükseliş = geç alım riski"""
    try:
        son_kapanis = df['Close'].iloc[-1]
        pencere = min(252, len(df))
        yuksek_52h = df['High'].iloc[-pencere:].max()
        zirve_yakin = (son_kapanis >= yuksek_52h * 0.97)  # Zirveye %3 yakın
        son10_kapanis = df['Close'].iloc[-11] if len(df) >= 11 else df['Close'].iloc[0]
        hizli_yukselis = ((son_kapanis - son10_kapanis) / son10_kapanis * 100) >= 20
        return bool(zirve_yakin or hizli_yukselis), bool(zirve_yakin), bool(hizli_yukselis)
    except Exception:
        return False, False, False

# --- YENİ: VOLATİLİTE KALİTESİ ---
def volatilite_kalitesi_hesapla(df, atr_val):
    """ATR/Fiyat oranı %1-5 arası ideal: çok düşük = sıkışık, çok yüksek = gürültülü"""
    try:
        son_kapanis = df['Close'].iloc[-1]
        if son_kapanis <= 0:
            return False
        oran = (atr_val / son_kapanis) * 100
        return bool(1.0 <= oran <= 5.0)
    except Exception:
        return False

# --- YENİ: GÜNLÜK vs HAFTALIK SİNYAL SINIFLANDIRMASI ---
def sinyal_turu_belirle(item_data):
    """Hesaplanan indikatörlere göre sinyalin günlük mi haftalık mı olduğunu belirle."""
    gunluk_puan  = 0
    haftalik_puan = 0

    # Günlük sinyal için güçlü göstergeler
    if item_data.get('ema_crossover_yukari'):  gunluk_puan  += 3
    if item_data.get('hacim_yuksek'):          gunluk_puan  += 2
    if item_data.get('patlama_adayi'):         gunluk_puan  += 2
    if item_data.get('mum_bullish'):           gunluk_puan  += 2
    if item_data.get('stoch_k', 50) < 40:     gunluk_puan  += 1

    # Haftalık sinyal için güçlü göstergeler
    if item_data.get('trend_yukselis'):        haftalik_puan += 3
    if item_data.get('haftalik_yukselis'):     haftalik_puan += 3
    if item_data.get('birikim_raw'):           haftalik_puan += 2
    if item_data.get('sikisma'):               haftalik_puan += 2
    if item_data.get('rs_guclu'):              haftalik_puan += 1

    if gunluk_puan >= 4 and gunluk_puan > haftalik_puan:
        return 'gunluk'
    elif haftalik_puan >= 4:
        return 'haftalik'
    else:
        return 'genel'

# =========================================================
# ERTESİ GÜN ANALİZ SİSTEMİ
# =========================================================

def kapanis_gucu_hesapla(df):
    """Kapanış gücü: fiyat günün neresinde kapandı? (0-100%)
    100 = tam zirvede kapandı (boğa), 0 = tam dipte kapandı (ayı)"""
    try:
        gun_yuksek = df['High'].iloc[-1]
        gun_dusuk  = df['Low'].iloc[-1]
        kapanis    = df['Close'].iloc[-1]
        aralik     = gun_yuksek - gun_dusuk
        if aralik <= 0:
            return 50.0
        return round(((kapanis - gun_dusuk) / aralik) * 100, 1)
    except Exception:
        return 50.0

def gun_ici_oruntu_tespit(df):
    """Gün içi kalıp tespiti: Inside Bar, Outside Bar, Güçlü/Zayıf Kapanış.
    Döndürür: (açıklama_str, puan) — puan ertesi gün skoru için eklenir."""
    try:
        if len(df) < 2:
            return "Belirsiz", 0
        bH = df['High'].iloc[-1];  bL = df['Low'].iloc[-1]
        bO = df['Open'].iloc[-1]; bC = df['Close'].iloc[-1]
        dH = df['High'].iloc[-2]; dL = df['Low'].iloc[-2]
        aralik = bH - bL
        kap_guc = ((bC - bL) / aralik * 100) if aralik > 0 else 50
        # Inside Bar
        if bH <= dH and bL >= dL:
            return "🔲 Inside Bar", 5
        # Outside Bar
        if bH > dH and bL < dL:
            return ("📦 Ext.Boğa", 8) if bC > (bH+bL)/2 else ("📦 Ext.Ayı", -8)
        # Güçlü kapanış
        if kap_guc >= 75 and bC > bO:
            return "💪 Güçlü Kap.", 12
        # Zayıf kapanış
        if kap_guc <= 25:
            return "😞 Zayıf Kap.", -12
        # Orta pozitif
        if kap_guc >= 55:
            return "📈 Poz. Kap.", 5
        return "➖ Normal Kap.", 0
    except Exception:
        return "Belirsiz", 0

def ardisik_yukselen_dipler(df, gun=3):
    """Son N günde her günün dibi bir öncekinden yüksek mi? (Güçlü yükseliş trendi)"""
    try:
        if len(df) < gun + 1:
            return False
        for i in range(-gun, 0):
            if df['Low'].iloc[i] <= df['Low'].iloc[i-1]:
                return False
        return True
    except Exception:
        return False

def ertesi_gun_skoru_hesapla(df, rsi_val, rvol, trend_yukselis, haftalik_yukselis,
                              mum_bullish, ema_crossover_yukari, gec_alim_riski,
                              piyasa_pozitif, roc10, adx_val, stoch_k_val):
    """Ertesi gün performans tahmini skoru (0-100).
    Geçmiş istatistiksel kalıplara dayalı olasılık skoru — kesin tahmin değildir."""
    try:
        puan = 0

        # 1. Kapanış Gücü — en kritik faktör (maks 25)
        kg = kapanis_gucu_hesapla(df)
        if   kg >= 80: puan += 25
        elif kg >= 65: puan += 18
        elif kg >= 50: puan += 10
        elif kg >= 35: puan +=  3
        else:          puan -= 12

        # 2. Hacim teyidi (maks 20)
        if   rvol >= 2.0: puan += 20
        elif rvol >= 1.5: puan += 14
        elif rvol >= 1.0: puan +=  8
        else:             puan +=  2

        # 3. Trend uyumu (maks 20)
        if trend_yukselis is True and haftalik_yukselis is True: puan += 20
        elif trend_yukselis is True:                             puan += 12
        elif haftalik_yukselis is True:                          puan +=  8

        # 4. Gün içi kalıp (maks 12)
        _, oruntu_puani = gun_ici_oruntu_tespit(df)
        puan += oruntu_puani

        # 5. Momentum ROC10 (maks 10)
        if   roc10 > 5: puan += 10
        elif roc10 > 2: puan +=  7
        elif roc10 > 0: puan +=  4
        else:           puan -=  5

        # 6. RSI ideal bölge (maks 10)
        if   40 <= rsi_val <= 60: puan += 10  # En iyi: hareket odası var
        elif 35 <= rsi_val <= 65: puan +=  5
        elif rsi_val >= 75:       puan -= 10  # Aşırı alım → ertesi gün düşme riski
        elif rsi_val <= 25:       puan -=  5

        # 7. Mum formasyonu (maks 10)
        if mum_bullish:            puan += 10

        # 8. EMA Crossover (maks 8)
        if ema_crossover_yukari:   puan +=  8

        # 9. ADX trend gücü (maks 7)
        if   adx_val >= 30: puan += 7
        elif adx_val >= 25: puan += 4

        # 10. Ardışık yükselen dipler (maks 8)
        if ardisik_yukselen_dipler(df, 3): puan += 8

        # 11. StochRSI pozisyon — en iyi alan: aşağıdan yukarı (maks 5)
        if 20 <= stoch_k_val <= 50: puan += 5

        # 12. Piyasa genel durumu (maks 5)
        if piyasa_pozitif: puan += 5

        # CEZA: Geç alım riski — zirvede, geri çekilme olası
        if gec_alim_riski: puan -= 20

        return max(0, min(100, puan))
    except Exception:
        return 50

# --- YENİ: MUM FORMASYONU TESPİTİ ---
def mum_formasyonu_tara(df):
    """Son 3 mumda boğa formasyonu tespiti"""
    try:
        if len(df) < 3:
            return "Yok", False
        o = df['Open']
        h = df['High']
        l = df['Low']
        c = df['Close']
        o1, h1, l1, c1 = o.iloc[-3], h.iloc[-3], l.iloc[-3], c.iloc[-3]
        o2, h2, l2, c2 = o.iloc[-2], h.iloc[-2], l.iloc[-2], c.iloc[-2]
        o3, h3, l3, c3 = o.iloc[-1], h.iloc[-1], l.iloc[-1], c.iloc[-1]
        body3 = abs(c3 - o3)
        range3 = h3 - l3 if h3 != l3 else 0.0001
        alt_golge3 = min(o3, c3) - l3
        ust_golge3 = h3 - max(o3, c3)
        # Çekiç
        if alt_golge3 >= 2 * body3 and ust_golge3 <= body3 * 0.5 and c3 > o3:
            return "🔨 Çekiç", True
        # Boğa Yutan
        if c2 < o2 and c3 > o3 and c3 >= o2 and o3 <= c2:
            return "🟢 Boğa Yutan", True
        # Sabah Yıldızı
        if (c1 < o1 and abs(c2 - o2) < (h2 - l2) * 0.35 and
                c3 > o3 and c3 > (o1 + c1) / 2):
            return "⭐ Sabah Yıldızı", True
        # Pin Bar (uzun alt gölge)
        if alt_golge3 >= range3 * 0.6 and c3 > o3:
            return "📌 Pin Bar", True
        # Doji (kararsızlık — nötr ama dikkate değer)
        if body3 <= range3 * 0.1:
            return "✚ Doji", False
        return "Yok", False
    except Exception:
        return "Yok", False

# --- YENİ: DESTEK / DİRENÇ SEVİYELERİ ---
def destek_direnc_hesapla(df):
    """52 haftalık H/L + Fibonacci + Pivot destek/direnç hesapla"""
    try:
        son_kapanis = df['Close'].iloc[-1]
        pencere = min(252, len(df))
        yuksek_52h = df['High'].iloc[-pencere:].max()
        dusuk_52h  = df['Low'].iloc[-pencere:].min()
        fark = yuksek_52h - dusuk_52h
        fib_236 = yuksek_52h - fark * 0.236
        fib_382 = yuksek_52h - fark * 0.382
        fib_500 = yuksek_52h - fark * 0.500
        fib_618 = yuksek_52h - fark * 0.618
        # Haftalık pivot
        pivot_p = (df['High'].iloc[-6:-1].max() + df['Low'].iloc[-6:-1].min() + df['Close'].iloc[-2]) / 3
        pivot_r1 = 2 * pivot_p - df['Low'].iloc[-6:-1].min()
        pivot_s1 = 2 * pivot_p - df['High'].iloc[-6:-1].max()
        seviyeler = sorted([dusuk_52h, fib_618, fib_500, fib_382, fib_236,
                            pivot_s1, pivot_p, pivot_r1, yuksek_52h])
        seviyeler_yukarda = [s for s in seviyeler if s > son_kapanis * 1.001]
        seviyeler_asagida = [s for s in seviyeler if s < son_kapanis * 0.999]
        yakin_direnc = min(seviyeler_yukarda) if seviyeler_yukarda else yuksek_52h
        yakin_destek = max(seviyeler_asagida) if seviyeler_asagida else dusuk_52h
        destek_mesafe = round((son_kapanis - yakin_destek) / son_kapanis * 100, 1)
        direnc_mesafe = round((yakin_direnc - son_kapanis) / son_kapanis * 100, 1)
        return {
            "yuksek_52h":      round(yuksek_52h, 2),
            "dusuk_52h":       round(dusuk_52h, 2),
            "yakin_destek":    round(yakin_destek, 2),
            "yakin_direnc":    round(yakin_direnc, 2),
            "destek_mesafe":   destek_mesafe,
            "direnc_mesafe":   direnc_mesafe,
            "destek_uzerinde": bool(destek_mesafe <= 6),
            "direnc_yakin":    bool(0 < direnc_mesafe <= 2),
            "fib_382":         round(fib_382, 2),
            "fib_618":         round(fib_618, 2),
        }
    except Exception:
        sk = df['Close'].iloc[-1] if not df.empty else 1
        return {"yuksek_52h": sk*1.5, "dusuk_52h": sk*0.5, "yakin_destek": sk*0.95,
                "yakin_direnc": sk*1.1, "destek_mesafe": 5.0, "direnc_mesafe": 10.0,
                "destek_uzerinde": False, "direnc_yakin": False,
                "fib_382": sk*1.05, "fib_618": sk*0.97}

# --- YENİ: HAFTALIK TREND ---
def haftalik_trend_al(ticker):
    """Haftalık zaman diliminde ana trend yönünü belirle (EMA10w > EMA20w)"""
    try:
        df_w = yf.Ticker(ticker).history(period="2y", interval="1wk", timeout=5)
        if df_w.empty or len(df_w) < 20:
            return None, None, None
        ema10w = df_w['Close'].ewm(span=10, adjust=False).mean()
        ema20w = df_w['Close'].ewm(span=20, adjust=False).mean()
        rsi_w  = rsi_hesapla(df_w['Close'], 14)
        haftalik_yukselis = bool(ema10w.iloc[-1] > ema20w.iloc[-1])
        haftalik_rsi      = round(rsi_w.iloc[-1], 1)
        haftalik_degisim  = round(
            (df_w['Close'].iloc[-1] - df_w['Close'].iloc[-2]) / df_w['Close'].iloc[-2] * 100, 2)
        return haftalik_yukselis, haftalik_rsi, haftalik_degisim
    except Exception:
        return None, None, None

# --- YENİ: PİYASA GENELİ DURUMU ---
def piyasa_durumu_al():
    """BIST100, S&P500, BTC günlük trend durumunu döndür"""
    def _endeks_kontrol(sembol, esik=-0.5):
        try:
            df = yf.Ticker(sembol).history(period="30d", interval="1d", timeout=4)
            if df.empty or len(df) < 5:
                return {"degisim": 0, "yukari": True, "pozitif": True, "getiri_10g": 0}
            degisim = (df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2] * 100
            ema20   = df['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
            getiri_10g = (df['Close'].iloc[-1] - df['Close'].iloc[-11]) / df['Close'].iloc[-11] * 100 \
                         if len(df) >= 11 else 0
            return {
                "degisim":    round(degisim, 2),
                "yukari":     bool(df['Close'].iloc[-1] > ema20),
                "pozitif":    bool(degisim > esik),
                "getiri_10g": round(getiri_10g, 2),
            }
        except Exception:
            return {"degisim": 0, "yukari": True, "pozitif": True, "getiri_10g": 0}
    return {
        "bist": _endeks_kontrol("XU100.IS",  esik=-0.5),
        "spy":  _endeks_kontrol("SPY",        esik=-0.5),
        "btc":  _endeks_kontrol("BTC-USD",    esik=-1.0),
    }

# --- GELİŞTİRİLMİŞ TEK TEK SEMBOL TARAMA FONKSİYONU (v8 MAX KAZANÇ) ---
def sembol_tara(ticker, piyasa, usd_try, acik_mi, piyasa_durumu=None, endeks_getiri=None):
    try:
        df = yf.Ticker(ticker).history(period="1y", interval="1d", timeout=5)
        if df.empty or len(df) < 30:
            return None
        
        yeterli_veri_var = len(df) >= 200

        son_kapanis    = df['Close'].iloc[-1]
        onceki_kapanis = df['Close'].iloc[-2]
        degisim = round(((son_kapanis - onceki_kapanis) / onceki_kapanis) * 100, 2)

        # --- RSI ---
        df['RSI'] = rsi_hesapla(df['Close'], 14)
        rsi_val = round(df['RSI'].iloc[-1], 2) if not pd.isna(df['RSI'].iloc[-1]) else 50

        # --- EMA ---
        df['EMA21'] = df['Close'].ewm(span=21, adjust=False).mean()
        ema21_val = df['EMA21'].iloc[-1]
        trend_yukselis = None
        if yeterli_veri_var:
            ema50_val  = df['Close'].ewm(span=50,  adjust=False).mean().iloc[-1]
            ema200_val = df['Close'].ewm(span=200, adjust=False).mean().iloc[-1]
            trend_yukselis = bool(ema50_val > ema200_val)

        # --- ROC (10 günlük momentum) ---
        roc10 = round(((son_kapanis - df['Close'].iloc[-11]) / df['Close'].iloc[-11]) * 100, 2) \
                if len(df) >= 11 else 0.0

        # --- ATR ---
        df['ATR'] = atr_hesapla(df, 14)
        atr_val = df['ATR'].iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            atr_val = son_kapanis * 0.02

        # --- Hacim ---
        hacim_ort  = df['Volume'].rolling(window=20).mean().iloc[-1]
        rvol       = round(df['Volume'].iloc[-1] / hacim_ort, 2) if hacim_ort > 0 else 1.0
        hacim_yuksek  = bool(rvol >= 1.5)
        hacim_kurumus = False
        if len(df) >= 25:
            son5_hacim    = df['Volume'].iloc[-6:-1].mean()
            hacim_kurumus = bool(son5_hacim < hacim_ort * 0.7)

        # --- Bollinger Sıkışma ---
        sikisma = False
        if len(df) >= 130:
            genislik = bollinger_genislik_hesapla(df, 20, 2)
            gecerli  = genislik.dropna()
            if len(gecerli) >= 120:
                esik    = gecerli.iloc[-120:].quantile(0.2)
                sikisma = bool(genislik.iloc[-1] <= esik)

        # --- OBV Birikim/Dağıtım ---
        birikim = dagitim = False
        if len(df) >= 15:
            obv           = obv_hesapla(df)
            obv_degisim   = obv.iloc[-1] - obv.iloc[-11]
            fiyat_deg_10  = abs((son_kapanis - df['Close'].iloc[-11]) / df['Close'].iloc[-11] * 100)
            birikim  = bool(obv_degisim > 0 and fiyat_deg_10 < 3)
            dagitim  = bool(obv_degisim < 0 and fiyat_deg_10 < 3)

        # --- DMI / ADX ---
        di_plus, di_minus, adx = dmi_adx_hesapla(df, 14)
        di_yukselis_baskin = bool(di_plus.iloc[-1] > di_minus.iloc[-1])
        adx_val = round(adx.iloc[-1], 2) if not pd.isna(adx.iloc[-1]) else 20.0

        # --- MACD ---
        macd_line, signal_line, macd_hist = macd_hesapla(df['Close'], 12, 26, 9)
        macd_val      = round(macd_line.iloc[-1],   4) if not pd.isna(macd_line.iloc[-1])   else 0.0
        macd_sig      = round(signal_line.iloc[-1], 4) if not pd.isna(signal_line.iloc[-1]) else 0.0
        macd_hist_val = round(macd_hist.iloc[-1],   4) if not pd.isna(macd_hist.iloc[-1])   else 0.0
        macd_bullish  = bool(macd_val > macd_sig)

        # --- Stochastic RSI ---
        stoch_k, stoch_d = stoch_rsi_hesapla(df['Close'])
        stoch_k_val = round(stoch_k.iloc[-1], 1)
        stoch_d_val = round(stoch_d.iloc[-1], 1)
        stoch_bullish = bool(stoch_k_val > stoch_d_val and stoch_k_val < 80 and stoch_k_val > 20)

        # --- Mum Formasyonu ---
        mum_adi, mum_bullish = mum_formasyonu_tara(df)

        # --- Destek / Direnç ---
        dr = destek_direnc_hesapla(df)

        # --- Haftalık Trend ---
        haftalik_yukselis, haftalik_rsi, haftalik_degisim = haftalik_trend_al(ticker)

        # --- YENİ: EMA9/21 Crossover ---
        ema_crossover_yukari, ema_crossover_asagi = ema_crossover_hesapla(df)

        # --- YENİ: Hacim Güç Oranı ---
        hacim_guc_orani = hacim_guc_orani_hesapla(df, 10)
        hacim_guc_pozitif = bool(hacim_guc_orani >= 1.3)

        # --- YENİ: RSI Uyumsuzluğu (Bullish Divergence) ---
        rsi_uyumsuzlugu = rsi_uyumsuzlugu_hesapla(df, 20)

        # --- YENİ: Geç Alım Riski ---
        gec_alim_riski, zirve_yakin, hizli_yukselis = gec_alim_riski_hesapla(df)

        # --- YENİ: Volatilite Kalitesi ---
        volatilite_kalitesi = volatilite_kalitesi_hesapla(df, atr_val)

        # --- YENİ: Bollinger Kırılış ---
        bollinger_kirilis = bool(sikisma and rvol >= 2.0)

        # --- Üçgen Yapısı ---
        ucgen_tip = ucgen_tipi_belirle(df, 20)

        # --- Yön Eğilimi ---
        yon_puan = 0
        if di_yukselis_baskin:          yon_puan += 1
        else:                           yon_puan -= 1
        if birikim:                     yon_puan += 1
        if dagitim:                     yon_puan -= 1
        if ucgen_tip == "yukselen":     yon_puan += 1
        elif ucgen_tip == "alcalan":    yon_puan -= 1
        if trend_yukselis is True:      yon_puan += 1
        elif trend_yukselis is False:   yon_puan -= 1
        if haftalik_yukselis is True:   yon_puan += 1
        elif haftalik_yukselis is False: yon_puan -= 1

        if yon_puan >= 2:    yon_bias = "Yukarı"
        elif yon_puan <= -2: yon_bias = "Aşağı"
        else:                yon_bias = "Nötr"

        # --- Hareket Aralığı ---
        menzil_genislik = df['High'].iloc[-30:].max() - df['Low'].iloc[-30:].min() \
                          if len(df) >= 30 else atr_val * 5
        menzil_yukari = son_kapanis + menzil_genislik
        menzil_asagi  = max(son_kapanis - menzil_genislik, son_kapanis * 0.5)

        # --- Temel Bayraklar ---
        rsi_genel   = (45 <= rsi_val <= 70)
        ema_uygun   = (son_kapanis > ema21_val)
        rsi_garanti = (45 <= rsi_val <= 65)
        patlama_adayi = bool(sikisma and birikim)

        # --- Alım Aralığı ---
        alim_min = ema21_val * 0.97
        alim_max = ema21_val * 1.01
        fark_yuzde = (son_kapanis - alim_max) / son_kapanis * 100
        if son_kapanis <= alim_max:   alim_durum = "ŞİMDİ"
        elif fark_yuzde <= 2.5:       alim_durum = "YAKIN"
        else:                         alim_durum = "BEKLE"

        # --- Stop / Hedef ---
        stop_val    = max(son_kapanis - atr_val * 2.0, son_kapanis * 0.9)
        kar_hedef_1 = son_kapanis + atr_val * 1.5
        kar_hedef_2 = son_kapanis + atr_val * 3.0
        risk        = son_kapanis - stop_val
        ro_1 = round((kar_hedef_1 - son_kapanis) / risk, 2) if risk > 0 else 0
        ro_2 = round((kar_hedef_2 - son_kapanis) / risk, 2) if risk > 0 else 0
        beklenen_kar_yuzde_1 = round(((kar_hedef_1 - son_kapanis) / son_kapanis) * 100, 2)
        beklenen_kar_yuzde_2 = round(((kar_hedef_2 - son_kapanis) / son_kapanis) * 100, 2)

        # --- YENİ: Göreceli Güç (RS) ---
        rs_guclu = False
        if endeks_getiri is not None:
            endeks_10g = endeks_getiri.get(piyasa["id"], 0)
            rs_guclu   = bool(roc10 > endeks_10g + 2)

        # =========================================================
        # v8 MAX KAZANÇ: GELİŞMİŞ AĞIRLIKLI SKORLAMA SİSTEMİ
        # =========================================================
        skor = 10  # Baz puan

        # Temel teknik indikatörler
        if rsi_genel:           skor += 10
        if ema_uygun:           skor += 15
        if trend_yukselis:      skor += 20   # Günlük ana trend
        if macd_bullish:        skor += 15

        # Trend gücü
        if adx_val >= 25:       skor += 12
        elif adx_val >= 20:     skor +=  5
        elif adx_val < 18:      skor -= 10

        # Hacim
        if rvol >= 1.5:         skor += 10
        elif rvol >= 1.0:       skor +=  5

        # Momentum
        if roc10 > 0:           skor +=  5

        # Risk/Ödül
        if ro_2 >= 1.5:         skor += 10

        # Özel sinyaller
        if sikisma:             skor += 10
        if hacim_kurumus:       skor +=  4
        if birikim:             skor += 10
        if patlama_adayi:       skor += 12

        # Yön eğilimi
        if yon_bias == "Yukarı": skor += 10
        elif yon_bias == "Aşağı": skor -= 15

        # Haftalık trend teyidi (en kritik faktör)
        if haftalik_yukselis is True:    skor += 25
        elif haftalik_yukselis is False: skor -= 20

        # Destek / Direnç
        if dr["destek_uzerinde"]:  skor += 10
        if dr["direnc_yakin"]:     skor -= 10  # Direçte satış baskısı var

        # Mum formasyonu
        if mum_bullish:            skor += 15

        # Stochastic RSI onayı
        if stoch_bullish:          skor +=  8
        elif stoch_k_val >= 80:    skor -=  5   # Aşırı alım

        # Göreceli Güç (endeks üstü performans)
        if rs_guclu:               skor += 15

        # Piyasa geneli durumu
        piyasa_pozitif = True
        if piyasa_durumu:
            pid = piyasa["id"]
            if pid == "TR":
                pd_info = piyasa_durumu.get("bist", {})
            elif pid == "US":
                pd_info = piyasa_durumu.get("spy", {})
            else:
                pd_info = piyasa_durumu.get("btc", {})
            piyasa_pozitif = pd_info.get("pozitif", True)
            if pd_info.get("yukari", True): skor += 10
            else:                           skor -= 20

        # =========================================================
        # YENİ: v8 MAX KAZANÇ EK SKORLARI
        # =========================================================

        # EMA9/21 Crossover — kısa vadeli en güçlü sinyal
        if ema_crossover_yukari:        skor += 20
        elif ema_crossover_asagi:       skor -= 15  # Ölüm çarpazı

        # Hacim Güç Oranı — akıllı para yönü
        if hacim_guc_orani >= 2.0:      skor += 15
        elif hacim_guc_orani >= 1.3:    skor += 10
        elif hacim_guc_orani < 0.7:     skor -= 10  # Düşen günler baskın

        # RSI Uyumsuzluğu — gizli boğa sinyali
        if rsi_uyumsuzlugu:             skor += 15

        # Geç Alım Riski — FALSE POSITIVE önleme (kritik ceza)
        if gec_alim_riski:              skor -= 25

        # Volatilite Kalitesi
        if volatilite_kalitesi:         skor +=  8

        # Bollinger Kırılış (Sıkışma + Yüksek Hacim)
        if bollinger_kirilis:            skor += 15

        # =========================================================
        # GARANTİ KOŞULLARI (Sıkı + Geç Alım Koruması)
        # =========================================================
        garanti = (
            skor >= 90 and
            ro_2 >= 1.1 and
            rsi_garanti and
            (trend_yukselis is True) and
            (haftalik_yukselis is True) and
            macd_bullish and
            (yon_bias != "Aşağı") and
            (adx_val >= 22.0) and
            piyasa_pozitif and
            not dr["direnc_yakin"] and
            not gec_alim_riski              # YENİ: geç alım sinyali değil
        )

        # Üçlü Onay (3 zaman dilimi uyumlu + tüm momentum pozitif)
        uclu_onay = bool(
            trend_yukselis is True and
            haftalik_yukselis is True and
            macd_bullish and
            stoch_bullish and
            yon_bias == "Yukarı" and
            birikim
        )

        skor_goster = skor + 5 if (garanti and rsi_garanti) else skor
        if ro_2 >= 2.5 and garanti: skor_goster += 5

        # =========================================================
        # YENİ: GÜVEN % (0-100 normalize)
        # =========================================================
        # Maksimum teorik skor hesabı
        MAX_SKOR = 260
        guven_yuzde = max(0, min(100, round((skor_goster / MAX_SKOR) * 100)))

        # =========================================================
        # ERTESİ GÜN ANALİZİ
        # =========================================================
        kapanis_gucu_pct  = kapanis_gucu_hesapla(df)
        gun_oruntu_adi, _ = gun_ici_oruntu_tespit(df)
        ardisik_yukselen  = ardisik_yukselen_dipler(df, 3)

        ertesi_gun_skoru_val = ertesi_gun_skoru_hesapla(
            df, rsi_val, rvol, trend_yukselis, haftalik_yukselis,
            mum_bullish, ema_crossover_yukari, gec_alim_riski,
            piyasa_pozitif, roc10, adx_val, stoch_k_val
        )

        # Tahmini açılış yönü
        if   ertesi_gun_skoru_val >= 72: acilis_yonu = "↑ Güçlü"
        elif ertesi_gun_skoru_val >= 58: acilis_yonu = "↗ Pozitif"
        elif ertesi_gun_skoru_val >= 42: acilis_yonu = "→ Nötr"
        elif ertesi_gun_skoru_val >= 28: acilis_yonu = "↘ Zayıf"
        else:                            acilis_yonu = "↓ Negatif"

        # Yarın AL: bugün + yarın aynı anda güçlü
        yarin_al = bool(
            ertesi_gun_skoru_val >= 65 and
            kapanis_gucu_pct >= 60 and
            (trend_yukselis is True) and
            not gec_alim_riski
        )

        # =========================================================
        # YENİ: DİNAMİK FİBONACCİ HEDEFLERİ
        # =========================================================
        # Hedef 1: ATR x 1.5 veya yakın Fibonacci direnci (hangisi düşükse değil, anlamlıysa Fib kullan)
        fib_direnc = dr.get("yakin_direnc", son_kapanis + atr_val * 2)
        fib_hedef_mesafe = fib_direnc - son_kapanis
        if fib_hedef_mesafe > atr_val * 0.5:  # Fibonacci hedefi mantıklıysa kullan
            kar_hedef_1 = min(son_kapanis + atr_val * 1.5, fib_direnc)
            kar_hedef_2 = fib_direnc if fib_hedef_mesafe > atr_val else son_kapanis + atr_val * 3.0
        else:
            kar_hedef_1 = son_kapanis + atr_val * 1.5
            kar_hedef_2 = son_kapanis + atr_val * 3.0

        ro_1 = round((kar_hedef_1 - son_kapanis) / risk, 2) if risk > 0 else 0
        ro_2 = round((kar_hedef_2 - son_kapanis) / risk, 2) if risk > 0 else 0
        beklenen_kar_yuzde_1 = round(((kar_hedef_1 - son_kapanis) / son_kapanis) * 100, 2)
        beklenen_kar_yuzde_2 = round(((kar_hedef_2 - son_kapanis) / son_kapanis) * 100, 2)

        # --- Kripto birimini TL'ye çevir ---
        if piyasa["id"] == "KR":
            for attr in ["son_kapanis", "ema21_val", "alim_min", "alim_max",
                         "stop_val", "kar_hedef_1", "kar_hedef_2",
                         "menzil_yukari", "menzil_asagi"]:
                locals_val = locals()[attr]
                locals()[attr] = locals_val * usd_try
            son_kapanis  *= usd_try
            ema21_val    *= usd_try
            alim_min     *= usd_try
            alim_max     *= usd_try
            stop_val     *= usd_try
            kar_hedef_1  *= usd_try
            kar_hedef_2  *= usd_try
            menzil_yukari *= usd_try
            menzil_asagi  *= usd_try
            if dr:
                dr["yakin_destek"] *= usd_try
                dr["yakin_direnc"] *= usd_try

        fiyat_guncel = round(son_kapanis, 2)
        gosterim_adi = ticker.replace(".IS", "").replace("-USD", "TRY")
        birim   = "₺" if piyasa["id"] in ["TR", "KR"] else "$"
        tv_link = tv_linki_olustur(gosterim_adi, piyasa["id"])

        if alim_max > stop_val and fiyat_guncel > stop_val:
            return {
                "symbol":              gosterim_adi,
                "fiyat":               fiyat_guncel,
                "birim":               birim,
                "degisim":             degisim,
                "rsi":                 rsi_val,
                "skor":                skor_goster,
                "alim_min":            round(alim_min, 2),
                "alim_max":            round(alim_max, 2),
                "alim_durum":          alim_durum,
                "stop":                round(stop_val, 2),
                "kar_hedef_1":         round(kar_hedef_1, 2),
                "kar_hedef_2":         round(kar_hedef_2, 2),
                "ro_1":                ro_1,
                "ro_2":                ro_2,
                "beklenen_kar_yuzde_1": beklenen_kar_yuzde_1,
                "beklenen_kar_yuzde_2": beklenen_kar_yuzde_2,
                "trend_yukselis":      trend_yukselis,
                "haftalik_yukselis":   haftalik_yukselis,
                "haftalik_rsi":        haftalik_rsi,
                "sikisma":             sikisma,
                "hacim_kurumus":       hacim_kurumus,
                "birikim":             birikim,
                "birikim_raw":         birikim,
                "dagitim":             dagitim,
                "yon_bias":            yon_bias,
                "ucgen_tip":           ucgen_tip,
                "menzil_yukari":       round(menzil_yukari, 2),
                "menzil_asagi":        round(menzil_asagi, 2),
                "roc10":               roc10,
                "garanti":             garanti,
                "uclu_onay":           uclu_onay,
                "acik_mi":             acik_mi,
                "hacim_yuksek":        hacim_yuksek,
                "piyasa_id":           piyasa["id"],
                "tv_link":             tv_link,
                "patlama_adayi":       patlama_adayi,
                "adx":                 adx_val,
                "macd_bullish":        macd_bullish,
                "macd_val":            macd_val,
                "macd_sig":            macd_sig,
                "macd_hist":           macd_hist_val,
                "rvol":                rvol,
                "stoch_k":             stoch_k_val,
                "stoch_d":             stoch_d_val,
                "mum_adi":             mum_adi,
                "mum_bullish":         mum_bullish,
                "rs_guclu":            rs_guclu,
                "destek":              dr["yakin_destek"],
                "direnc":              dr["yakin_direnc"],
                "destek_mesafe":       dr["destek_mesafe"],
                "direnc_mesafe":       dr["direnc_mesafe"],
                "yuksek_52h":          dr["yuksek_52h"],
                "dusuk_52h":           dr["dusuk_52h"],
                # v8 MAX KAZANÇ yeni alanlar
                "ema_crossover_yukari":  ema_crossover_yukari,
                "ema_crossover_asagi":   ema_crossover_asagi,
                "hacim_guc_orani":       hacim_guc_orani,
                "hacim_guc_pozitif":     hacim_guc_pozitif,
                "rsi_uyumsuzlugu":       rsi_uyumsuzlugu,
                "gec_alim_riski":        gec_alim_riski,
                "zirve_yakin":           zirve_yakin,
                "hizli_yukselis":        hizli_yukselis,
                "volatilite_kalitesi":   volatilite_kalitesi,
                "bollinger_kirilis":     bollinger_kirilis,
                "guven_yuzde":           guven_yuzde,
                # Ertesi Gün Analizi
                "kapanis_gucu_pct":      kapanis_gucu_pct,
                "gun_oruntu_adi":        gun_oruntu_adi,
                "ardisik_yukselen":      ardisik_yukselen,
                "ertesi_gun_skoru":      ertesi_gun_skoru_val,
                "acilis_yonu":           acilis_yonu,
                "yarin_al":              yarin_al,
            }
    except Exception as e:
        if VERBOSE:
            print(f"Hata ({ticker}): {str(e)[:80]}")
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
            padding: 1rem;
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
            transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
            cursor: pointer;
            user-select: none;
        }}

        .card:hover {{
            transform: translateY(-3px);
            border-color: rgba(255, 255, 255, 0.2);
            box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        }}

        .card.active {{
            border-color: var(--primary);
            box-shadow: 0 0 16px var(--primary-glow);
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
            font-size: 0.72rem;
        }}

        th {{
            background: rgba(10, 15, 30, 0.5);
            font-weight: 600;
            color: var(--text-muted);
            font-size: 0.65rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            padding: 0.6rem 0.5rem;
            border-bottom: 1px solid var(--border-color);
            cursor: pointer;
            user-select: none;
            transition: color 0.2s;
            white-space: nowrap;
        }}

        th:hover {{
            color: #fff;
        }}

        td {{
            padding: 0.5rem 0.5rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
            white-space: nowrap;
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
        .badge-gunluk { background: rgba(234, 88, 12, 0.15); color: #f97316; border: 1px solid rgba(249,115,22,0.3); }
        .badge-haftalik { background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(167,139,250,0.3); }
        .badge-late { background: rgba(239, 68, 68, 0.12); color: #fca5a5; border: 1px solid rgba(239,68,68,0.3); }
        .badge-div { background: rgba(6, 182, 212, 0.12); color: #67e8f9; border: 1px solid rgba(6,182,212,0.3); }
        .badge-cross { background: rgba(16, 185, 129, 0.15); color: #6ee7b7; border: 1px solid rgba(16,185,129,0.3); }

        .guven-bar-wrap { display: flex; align-items: center; gap: 5px; }
        .guven-bar { height: 5px; border-radius: 3px; background: rgba(255,255,255,0.08); flex: 1; overflow: hidden; }
        .guven-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
        .guven-label { font-size: 0.68rem; font-weight: 700; min-width: 28px; text-align: right; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-area">
                <div class="logo-icon">AG</div>
                <div class="logo-title">
                    <h1>Borsa &amp; Kripto Tarama Paneli</h1>
                    <p>Antigravity Engine v8 MAX KAZANÇ • Günlük &amp; Haftalık Optimizasyon</p>
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
            <div class="card" id="cardbox-total" onclick="cardFilter('total')" title="Tüm hisseleri göster">
                <div class="card-header">
                    <span>Toplam Taranan</span>
                    <span style="font-size:1.1rem">🔍</span>
                </div>
                <div class="card-value" id="card-total">0</div>
                <div class="card-desc">Aktif sembol listesi büyüklüğü</div>
            </div>
            <div class="card" id="cardbox-guaranteed" onclick="cardFilter('guaranteed')" title="Sadece Garanti sinyalleri göster">
                <div class="card-header">
                    <span>Garanti Sinyaller</span>
                    <span style="font-size:1.1rem">🛡️</span>
                </div>
                <div class="card-value text-green" id="card-guaranteed">0</div>
                <div class="card-desc">RSI, Trend ve Yön uyumlu AL sinyalleri</div>
            </div>
            <div class="card" id="cardbox-breakout" onclick="cardFilter('breakout')" title="Patlama adaylarını göster">
                <div class="card-header">
                    <span>Patlama Adayları</span>
                    <span style="font-size:1.1rem">🚀</span>
                </div>
                <div class="card-value" id="card-breakouts" style="color: #3b82f6 !important;">0</div>
                <div class="card-desc">Sıkışma + Birikim (Yüksek Kâr Adayı)</div>
            </div>
            <div class="card" id="cardbox-squeeze" onclick="cardFilter('squeeze')" title="Sıkışan hisseleri göster">
                <div class="card-header">
                    <span>Sıkışan (Squeeze)</span>
                    <span style="font-size:1.1rem">🌀</span>
                </div>
                <div class="card-value text-yellow" id="card-squeeze">0</div>
                <div class="card-desc">Bollinger squeeze durumundaki semboller</div>
            </div>
            <div class="card" id="cardbox-accumulation" onclick="cardFilter('accumulation')" title="OBV birikim hisselerini göster">
                <div class="card-header">
                    <span>Para Akışı Birikim</span>
                    <span style="font-size:1.1rem">📥</span>
                </div>
                <div class="card-value text-blue" id="card-accumulation">0</div>
                <div class="card-desc">Fiyat sabitken hacmi artan (OBV)</div>
            </div>
            <div class="card" id="cardbox-yarin" onclick="cardFilter('yarin')" title="Ertesi gün için güçlü setup">
                <div class="card-header">
                    <span>🔮 Yarın İçin</span>
                    <span style="font-size:1.1rem">🌙</span>
                </div>
                <div class="card-value" id="card-yarin" style="color:#a78bfa !important;">0</div>
                <div class="card-desc">Güçlü kapanış + ertesi gün skoru ≥65</div>
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
                <button class="filter-chip" id="chip-gunluk" onclick="toggleFilter('gunluk')">
                    📅 Günlük Sinyal
                </button>
                <button class="filter-chip" id="chip-haftalik" onclick="toggleFilter('haftalik')">
                    📆 Haftalık Swing
                </button>
                <button class="filter-chip" id="chip-crossover" onclick="toggleFilter('crossover')">
                    ✂️ EMA Crossover
                </button>
                <button class="filter-chip" id="chip-divergence" onclick="toggleFilter('divergence')">
                    🔄 RSI Div.
                </button>
                <button class="filter-chip" id="chip-yarin" onclick="toggleFilter('yarin')">
                    🔮 Yarın AL
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
                        <th onclick="handleSort('kar_hedef_2')">Hedef 2 (Fib)</th>
                        <th onclick="handleSort('ro_2')">R/O Oranı</th>
                        <th onclick="handleSort('beklenen_kar_yuzde_2')">Beklenen Kâr</th>
                        <th onclick="handleSort('guven_yuzde')">Güven %</th>
                        <th onclick="handleSort('ertesi_gun_skoru')">Ertesi Gün</th>
                        <th onclick="handleSort('skor')">Skor</th>
                        <th>Sinyaller</th>
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
        let filterGunluk = false;
        let filterHaftalik = false;
        let filterYarin = false;
        
        let sortColumn = 'ertesi_gun_skoru'; // default: ertesi gün skoruna göre
        let sortDirection = 'desc';

        // Başlangıç istatistikleri ve render
        function initDashboard() {{
            updateCards();
            renderTable();
        }}

        function updateCards() {{
            document.getElementById('card-total').innerText = dataset.length;
            document.getElementById('card-guaranteed').innerText = dataset.filter(x => x.garanti).length;
            document.getElementById('card-yarin').innerText = dataset.filter(x => x.yarin_al).length;
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
            }} else if (filter === 'gunluk') {{
                filterGunluk = !filterGunluk;
                document.getElementById('chip-gunluk').classList.toggle('active', filterGunluk);
            }} else if (filter === 'haftalik') {{
                filterHaftalik = !filterHaftalik;
                document.getElementById('chip-haftalik').classList.toggle('active', filterHaftalik);
            }} else if (filter === 'crossover') {{
                window._filterCrossover = !window._filterCrossover;
                document.getElementById('chip-crossover').classList.toggle('active', window._filterCrossover);
            }} else if (filter === 'divergence') {{
                window._filterDivergence = !window._filterDivergence;
                document.getElementById('chip-divergence').classList.toggle('active', window._filterDivergence);
            }} else if (filter === 'yarin') {{
                filterYarin = !filterYarin;
                document.getElementById('chip-yarin').classList.toggle('active', filterYarin);
            }}
            renderTable();
        }}

        let activeCardFilter = null;

        function cardFilter(type) {{
            // Tüm kartların active sınıfını kaldır
            document.querySelectorAll('.card').forEach(c => c.classList.remove('active'));

            // Tüm chip filtrelerini sıfırla
            filterGuaranteed = false;
            filterBreakout = false;
            filterSqueeze = false;
            filterAccumulation = false;
            filterNow = false;

            filterYarin = false;
            if (activeCardFilter === type) {{
                // Aynı karta tekrar tıklandı → filtreyi kaldır
                activeCardFilter = null;
            }} else {{
                activeCardFilter = type;
                // İlgili kartı aktif yap ve filtre uygula
                const cardEl = document.getElementById('cardbox-' + type);
                if (cardEl) cardEl.classList.add('active');

                if (type === 'guaranteed') filterGuaranteed = true;
                else if (type === 'breakout') filterBreakout = true;
                else if (type === 'squeeze') filterSqueeze = true;
                else if (type === 'accumulation') filterAccumulation = true;
                else if (type === 'yarin') filterYarin = true;
                // 'total' → filtre yok, tümünü göster
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
                if (filterGunluk) {{
                    const isGunluk = item.ema_crossover_yukari || item.patlama_adayi || (item.hacim_yuksek && item.mum_bullish);
                    if (!isGunluk) return false;
                }}
                if (filterHaftalik) {{
                    const isHaftalik = item.trend_yukselis && item.haftalik_yukselis && item.birikim_raw;
                    if (!isHaftalik) return false;
                }}
                if (window._filterCrossover && !item.ema_crossover_yukari) return false;
                if (window._filterDivergence && !item.rsi_uyumsuzlugu) return false;
                if (filterYarin && !item.yarin_al) return false;
                
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
                    durumBadge = '<span class="badge badge-garanti">🛡️ Garanti AL</span>';
                }} else {{
                    if (item.skor >= 90) durumBadge = '<span class="badge badge-izl">İzle</span>';
                    else if (item.skor >= 70) durumBadge = '<span class="badge badge-near">Potansiyel</span>';
                    else durumBadge = '<span class="badge badge-wait">Bekle</span>';
                }}

                // Sinyal badge'leri
                let signalBadges = '';
                if (item.ema_crossover_yukari) signalBadges += '<span class="badge badge-cross" title="EMA9 EMA21\'i yukarı kesti">✂️ EMA Cross</span> ';
                if (item.rsi_uyumsuzlugu) signalBadges += '<span class="badge badge-div" title="RSI Bullish Divergence — Gizli Boğa Sinyali">🔄 RSI Div</span> ';
                if (item.bollinger_kirilis) signalBadges += '<span class="badge badge-cross" title="Bollinger Sıkışmadan Yüksek Hacimle Kırılış">💥 BB Kırılış</span> ';
                if (item.gec_alim_riski) signalBadges += '<span class="badge badge-late" title="Geç Alım Riski: Zirvede veya Hızlı Yükselmiş">⚠️ Geç</span> ';
                const isGunluk = item.ema_crossover_yukari || item.patlama_adayi || (item.hacim_yuksek && item.mum_bullish);
                const isHaftalik = item.trend_yukselis && item.haftalik_yukselis && item.birikim_raw;
                if (isGunluk) signalBadges += '<span class="badge badge-gunluk">📅 Günlük</span> ';
                if (isHaftalik) signalBadges += '<span class="badge badge-haftalik">📆 Haftalık</span> ';

                let icons = '';
                if (item.hacim_yuksek) icons += '<span class="icon-badge" title="Yüksek Hacim">🔥</span>';
                if (item.sikisma) icons += '<span class="icon-badge" title="Bant Sıkışması (Breakout Yakın)">🌀</span>';
                if (item.birikim_raw) icons += '<span class="icon-badge" title="OBV Birikim (Akıllı Para Girişi)">📥</span>';
                if (item.patlama_adayi) icons += '<span class="icon-badge" title="PATLAMA POTANSİYELİ! 🚀">🚀</span>';
                if (item.ema_crossover_yukari) icons += '<span class="icon-badge" title="EMA Crossover">✂️</span>';
                if (item.rsi_uyumsuzlugu) icons += '<span class="icon-badge" title="RSI Divergence">🔄</span>';

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
                        <td style="min-width:80px;">
                            <div class="guven-bar-wrap">
                                <div class="guven-bar"><div class="guven-bar-fill" style="width:${{item.guven_yuzde || 0}}%; background: ${{(item.guven_yuzde||0) >= 70 ? '#10b981' : (item.guven_yuzde||0) >= 50 ? '#f59e0b' : '#ef4444'}};"></div></div>
                                <span class="guven-label" style="color:${{(item.guven_yuzde||0) >= 70 ? '#10b981' : (item.guven_yuzde||0) >= 50 ? '#f59e0b' : '#ef4444'}};">${{item.guven_yuzde || 0}}%</span>
                            </div>
                        </td>
                        <td style="min-width:105px; text-align:center;">
                            <div style="font-size:0.7rem; font-weight:700; color:${{(item.ertesi_gun_skoru||0)>=70?'#10b981':(item.ertesi_gun_skoru||0)>=50?'#f59e0b':'#9ca3af'}}">
                                ${{item.acilis_yonu || '→'}}
                            </div>
                            <div class="guven-bar" style="margin-top:3px;"><div class="guven-bar-fill" style="width:${{item.ertesi_gun_skoru||0}}%; background:${{(item.ertesi_gun_skoru||0)>=70?'#a78bfa':(item.ertesi_gun_skoru||0)>=50?'#f59e0b':'#ef4444'}};"></div></div>
                            <div style="font-size:0.65rem; color:#9ca3af; margin-top:2px;">${{item.ertesi_gun_skoru||0}}/100 ${{item.yarin_al?'🔮':''}} ${{item.ardisik_yukselen?'📶':''}}</div>
                            <div style="font-size:0.6rem; color:#6b7280;">${{item.gun_oruntu_adi||''}}</div>
                        </td>
                        <td style="text-align:center;"><strong>${{item.skor}}</strong></td>
                        <td style="max-width:160px; white-space: normal; line-height:1.5;">${{signalBadges || '–'}}</td>
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
                            sinyal_liste = []
                            if item.get("ema_crossover_yukari"): sinyal_liste.append("✂️ EMA Crossover")
                            if item.get("rsi_uyumsuzlugu"): sinyal_liste.append("🔄 RSI Divergence")
                            if item.get("bollinger_kirilis"): sinyal_liste.append("💥 Bollinger Kırılış")
                            if item.get("sikisma"): sinyal_liste.append("🌀 Sıkışma")
                            if item.get("birikim_raw"): sinyal_liste.append("📥 OBV Birikim")
                            if item.get("patlama_adayi"): sinyal_liste.append("🚀 Patlama Adayı")
                            if item.get("mum_bullish"): sinyal_liste.append(f"🕯️ {item.get('mum_adi','Formasyon')}")
                            if item.get("hacim_guc_pozitif"): sinyal_liste.append(f"📊 Hacim Güç:{item.get('hacim_guc_orani',1):.1f}x")
                            sinyal_metin = " | ".join(sinyal_liste) if sinyal_liste else "Yok"

                            # Sinyal türü: Günlük mi Haftalık mı?
                            is_gunluk = item.get("ema_crossover_yukari") or item.get("patlama_adayi") or (item.get("hacim_yuksek") and item.get("mum_bullish"))
                            is_haftalik = item.get("trend_yukselis") and item.get("haftalik_yukselis") and item.get("birikim_raw")
                            if is_gunluk and is_haftalik:
                                tur_metin = "📅 Günlük + 📆 Haftalık"
                            elif is_gunluk:
                                tur_metin = "📅 Günlük Sinyal"
                            elif is_haftalik:
                                tur_metin = "📆 Haftalık Swing"
                            else:
                                tur_metin = "📊 Genel Sinyal"

                            piyasa_durum_metni = "⚠️ <b>(Piyasa Kapalı - Hafta Sonu Sinyali)</b>\n" if not item["acik_mi"] else ""
                            guven = item.get('guven_yuzde', 0)
                            guven_bar = "🟢" * (guven // 20) + "⬜" * (5 - guven // 20)

                            mesaj = (
                                f"🛡️ <b>{item['symbol']} — GARANTİ AL SİNYALİ</b>\n"
                                f"{piyasa_durum_metni}"
                                f"🏷️ <b>Tür:</b> {tur_metin}\n"
                                f"🌍 <b>Piyasa:</b> {item['piyasa_id']} | 💹 <b>Güven:</b> {guven_bar} {guven}%\n"
                                f"💰 <b>Fiyat:</b> {deger_formatla(item['fiyat'])}{item['birim']} | RSI:{item['rsi']:.0f} | ADX:{item['adx']:.0f} | Skor:{item['skor']}\n"
                                f"📈 <b>Trend:</b> {'✅ Yükseliş' if item['trend_yukselis'] else '❓ Belirsiz'} | <b>Haftalık:</b> {'✅ Yükseliş' if item.get('haftalik_yukselis') else '⚠️ Zayıf'}\n"
                                f"📡 <b>Sinyaller:</b> {sinyal_metin}\n"
                                f"─────────────────\n"
                                f"📌 <b>Alım Aralığı:</b> {deger_formatla(item['alim_min'])} – {deger_formatla(item['alim_max'])} <i>({item['alim_durum']})</i>\n"
                                f"🛑 <b>Stop-Loss:</b> {deger_formatla(item['stop'])}{item['birim']}\n"
                                f"🎯 <b>Hedef-1:</b> {deger_formatla(item['kar_hedef_1'])}{item['birim']} (+{item['beklenen_kar_yuzde_1']:.0f}%)\n"
                                f"🚀 <b>Hedef-2 (Fib):</b> {deger_formatla(item['kar_hedef_2'])}{item['birim']} (+{item.get('beklenen_kar_yuzde_2', 0):.0f}%)\n"
                                f"⚖️ <b>R/O Oranı:</b> {item['ro_1']} / {item['ro_2']}\n"
                                f"─────────────────\n"
                                f"⚠️ <i>Yatırım tavsiyesi değildir.</i>"
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

        # =========================================================
        # AKSAM BİLDİRİMİ — Yarın İçin En İyi Setups (Piyasa kapandıktan sonra)
        # =========================================================
        try:
            simdi_ist = datetime.now(ISTANBUL_TZ)
            # TR piyasası 18:15'ten sonra veya US piyasası 23:00'dan sonra (TR saatiyle)
            aksam_mi = simdi_ist.hour >= 18
            if aksam_mi:
                # Tüm sonuçlardan ertesi gün skoru en yüksek 5 hisseyi seç
                yarin_adaylari = sorted(
                    [r for r in tum_sinyaller_listesi if r.get("ertesi_gun_skoru", 0) >= 60],
                    key=lambda x: x.get("ertesi_gun_skoru", 0),
                    reverse=True
                )[:5]

                if yarin_adaylari:
                    aksam_key = f"AKSAM_BILDIRIMI_{simdi_ist.strftime('%Y%m%d')}"
                    if aksam_key not in gonderilen_sinyaller:
                        satirlar = ""
                        for i, r in enumerate(yarin_adaylari, 1):
                            eg = r.get('ertesi_gun_skoru', 0)
                            yoru = r.get('acilis_yonu', '→')
                            kg   = r.get('kapanis_gucu_pct', 50)
                            ort  = r.get('gun_oruntu_adi', '')
                            satirlar += (
                                f"  {i}. <b>{r['symbol']}</b> ({r['piyasa_id']}) — "
                                f"Skor: <b>{eg}/100</b> | {yoru}\n"
                                f"     Kapanış Gücü: {kg:.0f}% | {ort}\n"
                                f"     Alım: {deger_formatla(r['alim_min'])}-{deger_formatla(r['alim_max'])}{r['birim']} | "
                                f"Stop: {deger_formatla(r['stop'])}{r['birim']} | "
                                f"H2: {deger_formatla(r['kar_hedef_2'])}{r['birim']}\n\n"
                            )
                        aksam_mesaj = (
                            f"🌙 <b>AKSAM TARАМASI — YARIN İÇİN ÖNERİLER</b>\n"
                            f"📅 {simdi_ist.strftime('%d.%m.%Y')} akşamı | Ertesi Gün Skoru'na Göre\n"
                            f"─────────────────────\n"
                            f"{satirlar}"
                            f"─────────────────────\n"
                            f"⚠️ <i>İstatistiksel tahmindir. Yatırım tavsiyesi değildir.</i>"
                        )
                        bildirim_gonder(aksam_mesaj)
                        gonderilen_sinyaller.add(aksam_key)
                        sinyalleri_kaydet(gonderilen_sinyaller)
                        print(Fore.MAGENTA + f"[🌙] Akşam bildirimi gönderildi ({len(yarin_adaylari)} aday)" + Style.RESET_ALL)
        except Exception as e:
            if VERBOSE:
                print(f"Akşam bildirimi hatası: {e}")

    except Exception as e:
        hata_mesaji = traceback.format_exc()
        hata_kaydet(hata_mesaji)
        print(Fore.RED + f"\n❌ KRİTİK HATA: {e}" + Style.RESET_ALL)
        print(Fore.YELLOW + f"Hata detayları 'hata_log.txt' dosyasına kaydedildi." + Style.RESET_ALL)
        raise

# === ANA PROGRAM BAŞLANGICI ===
print("=" * 70)
print("BORSA TARAMA ROBOTU v9 — ERTESİ GÜN ANALİZİ BAŞLIYOR")
print("SÜRÜM: v9.0 (EMA Cross | RSI Div | Kapanış Gücü | Ertesi Gün Skoru | Akşam Bildirimi)")
print("=" * 70)

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
    if not os.getenv("GITHUB_ACTIONS"):
        # Yalnızca lokal çalışmada kullanıcıdan giriş bekle
        print("Kapatmak için Enter tuşuna basın...")
        guvenli_giris_bekle()
    else:
        print("GitHub Actions: Program tamamlandı.")
