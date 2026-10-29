# Match The Lyrics

Şarkı + söz → satır zamanları → elle düzeltme → `.srt`. Düzeltmelerinden öğrenir.

Yerel çalışır: şarkıların ve sözlerin bilgisayarından çıkmaz. Almanca, Türkçe ve İngilizce satırlar aynı şarkıda karışık olabilir.

**Nasıl çalışır:** [Demucs](https://github.com/adefossez/demucs) vokali müzikten ayırır, Meta'nın MMS modeli sözleri vokale hizalar (forced alignment). Sen düzelttikçe küçük bir öğrenme modülü önerilerini sana göre ayarlar.

## Kurulum (Windows)

Gerekenler: Python 3.13, [ffmpeg](https://ffmpeg.org/) (`winget install Gyan.FFmpeg`). NVIDIA ekran kartı önerilir; CPU'da da çalışır ama yavaştır.

```bat
setup.bat
```

İlk şarkıda modeller (yaklaşık 1,3 GB) otomatik olarak indirilir.

## Başlatma

`start.bat` dosyasına çift tıkla. Tarayıcıda http://127.0.0.1:8765 açılır.

Veriler (projeler, ayrılmış vokaller, öğrenme modeli) depo dışında, `..\matchthelyrics-local\data` klasöründe tutulur. Başka bir klasör kullanmak için `MTL_DATA_DIR` ortam değişkenini ayarla. Bu klasörü yedeklemek öğrenilenleri korur.

## Kullanım

1. **Yeni şarkı**: Ses dosyasını seç ve sözleri yapıştır (her satır bir altyazı olur).
   Satır dilini etikete tıklayarak değiştirebilirsin. Ya da satır başına `[tr]`, `[de]`, `[en]` yazabilirsin.
   Tek başına `[tr]` yazılan bir satır, sonraki tüm satırları Türkçe yapar.
2. **Hizala**: RTX 4070'te 3-4 dakikalık bir şarkı yaklaşık 15-30 saniye sürer.
3. **Düzelt**: Blokları dalga formunda sürükle ya da kenarlarından uzat/kısalt.

   | Tuş | İşlev |
   |---|---|
   | Boşluk | Oynat / durdur |
   | Enter | Seçili satırı çal |
   | ↑ ↓ | Satır seç |
   | Q / W | Başlangıcı / bitişi imlecin olduğu yere al |
   | Z / X | Başlangıcı 50 ms geri / ileri al (Shift ile 10 ms) |
   | C / V | Bitişi 50 ms geri / ileri al (Shift ile 10 ms) |
   | N / Shift+N | Sonraki / önceki şüpheli satır |
   | A | Seçili satırı çapala / çapayı kaldır |

   "Sadece vokal" düğmesi, müzik olmadan dinleyip sınırları daha net duymanı sağlar.
4. **Kaydet ve indir**: Kaydetmek, düzeltmeni öğrenme verisine ekler.

   | Biçim | Ne için |
   |---|---|
   | `.srt` | Video altyazısı |
   | `.lrc` (satır) | Müzik çalarlar |
   | `.lrc` (kelime kelime) | Kelime zamanlı LRC |
   | `.ass` karaoke | Kelime kelime renklenen altyazı (Aegisub, VLC, mpv, ffmpeg) |

### Şüpheli satırlar ⚠

Hizalayıcının emin olmadığı satırlar kırmızı işaretlenir ve **N** ile aralarında gezilir. Bunlar genelde yanlış yere konmuş satırlardır. İşaret, satıra dokunduğunda kalkar.

### Çapalar ⚓

Doğru yerde olduğundan emin olduğun bir satırı **A** ile çapala. **↻ Çapalara göre hizala**, çapaları yerinde tutar ve diğer satırları çapaların arasındaki boşluklara yeniden hizalar. Böylece yanlış yere kaymış bir nakarat bölümünü tek bir düzeltmeyle toparlarsın. Bir satırı önerilen yerinden 1 saniyeden fazla taşırsan otomatik olarak çapalanır.

### Vokal ayırma kalitesi

| Model | Hız | Ne zaman |
|---|---|---|
| `htdemucs` | Hızlı (varsayılan) | Çoğu şarkı |
| `htdemucs_ft` | Yaklaşık 4 kat yavaş | Yoğun müzikli şarkılar; daha temiz vokal verir |

Yeni şarkı eklerken seçebilir ya da editördeki **Yüksek kalite vokal** düğmesiyle sonradan geçebilirsin. Geçişte çapalar korunur.

## Öğrenme

- **Seviye A**: Dil başına sistematik kayma. Birkaç şarkıdan sonra belirginleşir.
- **Seviye B**: Sınır düzeltme modeli (gradient boosting). En az 3 şarkı ve 150 satır birikince eğitilir. Görülmemiş şarkılarda Seviye A'dan daha iyiyse kullanılır.
- **SRT içe aktar**: Daha önce elle düzelttiğin SRT'leri şarkılarıyla birlikte ekleyerek öğrenmeyi hızlandırabilirsin.
- **Öğrenme** sayfasında, şarkı başına ne kadar düzeltme yapman gerektiğini zaman içinde görürsün.

## Geliştirme

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -m "not gpu"
.venv\Scripts\python.exe -m pytest -m gpu
node --test tests/js/util.test.mjs
```

- İlk komut hızlı testleri çalıştırır. Bu testlerde modeller sahte sürümlerle değiştirilir.
- İkinci komut, gerçek Demucs ve MMS modelleriyle uçtan uca testi çalıştırır. CUDA gerektirir.
- Üçüncü komut arayüz yardımcılarını test eder.

GitHub Actions, her push'ta GPU dışındaki testleri çalıştırır.

| Klasör | İçerik |
|---|---|
| `app/` | FastAPI sunucusu, vokal ayırma, hizalama (çapalı), öğrenme, SRT/LRC/ASS çıktıları |
| `static/` | Tarayıcı editörü (wavesurfer.js) |
| `tests/` | pytest ve Node testleri, sentetik test şarkısı |

## Lisans notu

MMS hizalama modelinin ağırlıkları CC-BY-NC 4.0 lisanslıdır, yani yalnızca ticari olmayan kullanıma açıktır. Ayrıntılar [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) dosyasında.
