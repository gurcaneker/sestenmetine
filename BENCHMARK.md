# Local Mode Whisper Benchmark (2026-07-28)

Bu doküman, `TRANSCRIPTION_BACKEND=local` (`backend/server.py` →
`_transcribe_local`) için yapılan performans optimizasyonunun ve
tiny/base/small/large-v3-turbo model karşılaştırmasının ölçüm sonuçlarını
kaydeder. Amaç: gerçek veriyle karar vermek, tahminle değil —
`WHISPER_MODEL_SIZE` ve `WHISPER_BATCH_SIZE` seçimi bu ölçümlere dayanıyor
ama env değişkeni olarak kalıyor (kod içinde sabitlenmedi), böylece kendi ses
verinizle farklı sonuç alırsanız `.env`'den değiştirebilirsiniz.

## Ortam

- Geliştirme makinesi: 16 çekirdek. **Hedef VPS 4 çekirdekli** — tüm ölçümler
  `taskset -c 0-3` ile 4 çekirdeğe kısıtlanarak yapıldı (VPS'i simüle etmek
  için); `cpu_threads` de buna göre 4 verildi.
- faster-whisper 1.2.1, ctranslate2 4.8.1, `compute_type=int8` (CPU), model
  cache'i ısınmış (ilk indirme süresi ölçümlere dahil değil).
- Ses: `test_fixtures/jfk.flac` (gerçek JFK konuşması, ~11s, tekli/temiz
  kayıt) ve ondan türetilmiş ~115s'lik sentetik bir kayıt (aynı konuşma 2s
  sessizlikle 9 kez art arda eklenerek oluşturuldu — VAD'ın birden fazla
  segment üretmesi için; batching'in faydası tek segmentli kısa bir klipte
  görünmez).

## Bulgu 1 — CPU thread oversubscription (gerçek bug)

Mevcut kod `cpu_threads=os.cpu_count()` kullanıyordu. `os.cpu_count()` **host
makinenin toplam çekirdek sayısını döner, cgroup/container/`taskset` CPU
kısıtlamasını görmez.** Bir VPS/Docker container'da gerçek pay 4 çekirdek
olsa bile host daha fazla çekirdeğe sahipse (veya bir cgroup limiti varsa),
`os.cpu_count()` bunu yanlış yüksek raporlar → ctranslate2 gerçekte
zamanlanabilecek olandan fazla OpenMP thread'i açar → thread contention/
oversubscription (gözlemlenen "~117% CPU" belirtisiyle uyumlu: thread'ler
birbirini bekliyor, gerçek paralel iş yapmıyor).

Doğrulama (`taskset -c 0-3` ile 4 çekirdeğe kısıtlı, `jfk.flac`, model=small,
non-batched):

| cpu_threads | Wall time | Kullanılan çekirdek (cpu_time/wall) |
|---|---|---|
| 16 (`os.cpu_count()` — hatalı, gerçek limit 4) | 3.42s | 2.86 |
| 4 (`len(os.sched_getaffinity(0))` — düzeltilmiş) | 2.257s | 3.65 |

**~%34 daha hızlı ve daha verimli çekirdek kullanımı.** Düzeltme:
`os.sched_getaffinity(0)` (Linux'a özgü, cgroup/`taskset`-farkında) kullanan
yeni bir `_local_cpu_threads()` fonksiyonu eklendi; `os.sched_getaffinity`
yoksa (Linux dışı) `os.cpu_count()`'a düşer. Bkz.
`backend/server.py` `_local_cpu_threads()`.

## Bulgu 2 — BatchedInferencePipeline (asıl hız kazancı)

faster-whisper'ın `BatchedInferencePipeline`'ı VAD ile bulunan konuşma
segmentlerini tek tek değil toplu (batch) işliyor. Tek bir segmentin decode
döngüsü çekirdekler arası iyi paralelleşmiyor (sıralı token-by-token beam
search); bir batch segment birlikte işlendiğinde gerçek paralellik oluşuyor.

~115s'lik çok-segmentli (9 segment) sentetik kayıtta, `cpu_threads=4`,
`batch_size=8`:

| Model | Non-batched (eski) | Batched (yeni) | Hızlanma |
|---|---|---|---|
| tiny  | 14.94s | 2.09s  | **7.2x** |
| base  | 32.93s | 3.87s  | **8.5x** |
| small | 81.02s | 11.08s | **7.3x** |

(Not: non-batched `base`/`small` çıktısında, aynı cümlenin 9 kez art arda
tekrarı yüzünden bazı tekrar/halüsinasyon artefaktları gözlendi — muhtemelen
`condition_on_previous_text`'in yapay tekrara tepkisi; gerçek, çeşitli
içerikli bir kayıtta beklenmez, ama bu da batching lehine ek bir gözlem.)

### batch_size seçimi (4 / 8 / 16)

Aynı kayıt, `cpu_threads=4`, model=small:

| batch_size | Wall time |
|---|---|
| 4  | 11.04s |
| 8  | 11.08s |
| 16 | 10.97s |

Bu test dosyasında (~9 segment) anlamlı bir fark yok — batch boyutu segment
sayısını geçtiği için pratikte hepsi tek seferde işleniyor. **`8` varsayılan
olarak seçildi**: daha uzun/çok-segmentli gerçek kayıtlarda (toplantı,
röportaj) hâlâ makul bir bellek/paralellik dengesi sunuyor. `WHISPER_BATCH_SIZE`
env değişkeni olarak `.env`'den değiştirilebilir.

## Bulgu 3 — Model boyutu karşılaştırması (tiny / base / small)

Batching aktif, `cpu_threads=4`, `batch_size=8`.

**Tek geçişlik, temiz kayıt** (`jfk.flac`, ~11s, tek segment):

| Model | Süre | Gerçek-zaman oranı | Transkript |
|---|---|---|---|
| tiny  | 0.51s | 21.6x gerçek zamandan hızlı | "And so my fellow Americans ask not what your country can do for you, ask what you can do for your country." |
| base  | 0.83s | 13.3x | "And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country." |
| small | 2.21s | 5.0x | "And so my fellow Americans, ask not what your country can do for you, ask what you can do for your country." |

**Kelime düzeyinde fark yok** — üç model de aynı kelimeleri doğru üretti;
tek fark `tiny`'nin "Americans" sonrası virgülü atlaması (noktalama, anlam
değil).

**Çok-segmentli, ~115s'lik sentetik kayıt** (aynı cümle 9 kez tekrar —
noktalama tutarlılığının uzun kayıtlarda nasıl bozulduğunu görmek için):
her üç model de kelimeleri doğru transkribe etti, ama tekrar sayısı arttıkça
noktalama/büyük harf tutarlılığı düşüyor (muhtemelen `condition_on_
previous_text`'in tekrarlayan içerikte "kararsızlaşması"): `tiny` hiç
noktalama tutturamadı, `base` ~3 tekrar sonra noktalamayı kaybetti, `small`
~5 tekrar sonra kaybetti — yani `small` noktalamayı en uzun süre koruyor,
ama üçü de sonunda düşüyor.

### Değerlendirme

Bu test setinde (temiz, tek konuşmacılı, net bir tarihi kayıt) **model
boyutunun kelime doğruluğuna ölçülebilir bir etkisi yok** — `tiny` bile
`small` ile aynı kelimeleri üretti. Bunun nedeni muhtemelen test kaydının
projenin asıl hedef kullanım senaryosunu (README.md: "düşük kaliteli/düşük
frekanslı kayıtlar — röportaj, saha kaydı, toplantı notu") temsil
etmemesi — gürültülü/aksanlı/düşük kaliteli sesle model boyutu farkının
daha belirgin olması beklenir, ama elimizde böyle bir test fixture'ı yok.

**Öneri:** Karar vermeden önce, gerçek kullanım senaryonuza yakın (gürültülü/
düşük kaliteli) bir kayıtla kendiniz test edin — `WHISPER_MODEL_SIZE`'ı
`.env`'de değiştirip aynı dosyayı tekrar gönderin. Bu benchmark'tan çıkan
somut, güvenle söylenebilecek sonuç: **hız farkı büyük** (tiny, small'dan
~4.3x daha hızlı), **noktalama tutarlılığı** uzun kayıtlarda `small` lehine
hafif bir avantaj gösteriyor, ama **kelime doğruluğu** bu test setinde
ayırt edici değildi.

## Bulgu 4 — large-v3-turbo (2026-07-28)

faster-whisper 1.2.1'in tanıdığı model listesi (`faster_whisper.available_models()`)
`large-v3-turbo`'yu içeriyor — `WHISPER_MODEL_SIZE=large-v3-turbo` **kod
değişikliği gerektirmeden** çalışıyor (`WHISPER_MODEL_SIZE` zaten serbest
metin, bir whitelist'e karşı doğrulanmıyor); gerçek sunucu üzerinden
(`TRANSCRIPTION_BACKEND=local`, `WHISPER_MODEL_SIZE=large-v3-turbo`) canlı bir
`/api/transcribe` isteğiyle de doğrulandı. İlk kullanımda modeli indiriyor
(~1.6 GB, `~/.cache/huggingface`'e).

### Hız (batching aktif, `cpu_threads=4`, `batch_size=8`)

| Kayıt | small | large-v3-turbo | Yavaşlama |
|---|---|---|---|
| `jfk.flac` (~11s, İngilizce, tek segment) | 2.15s | 7.79s | **3.6x** |
| ~115s sentetik, çok-segmentli (İngilizce) | 11.08s | 36.72s | **3.3x** |
| Türkçe örnek (~20s, bkz. aşağıda) | 3.76s | 9.76s | **2.6x** |

`large-v3-turbo`, `small`'dan tutarlı şekilde ~3x daha yavaş — beklenen bir
sonuç (çok daha büyük bir model, hâlâ CPU'da int8 ile). 4 çekirdekli VPS'te
gerçek zamanlı kullanım için hâlâ yeterince hızlı (~20s'lik bir kayıt için
~10s işlem süresi, yani gerçek zamandan ~2x hızlı) ama `small`'a göre gözle
görülür bir gecikme farkı var.

### Doğruluk — İngilizce (`jfk.flac`, "ask not what your country...")

Önceki bulguyla (Bulgu 3) aynı: bu temiz kayıtta **kelime düzeyinde fark yok**,
`large-v3-turbo` da `tiny`/`small` ile birebir aynı, doğru transkripti
üretti. Bu temiz test setinde büyük model bir avantaj göstermedi.

### Doğruluk — Türkçe (yeni test verisi)

Projenin gerçek hedef dili Türkçe olduğu ve `test_fixtures/`'ta gerçek bir
Türkçe kayıt bulunmadığı için, gTTS ile (bu ölçüm için geçici olarak kurulup
sonra kaldırıldı — projeye bağımlılık olarak eklenmedi) gerçek bir Türkçe
sesli kayıt sentezlendi (~20s, Türkçe'ye özgü karakterler — İstanbul, üçte,
çeyreklik, güneşli — içeren 3 cümle):

> Kaynak metin: "Merhaba, bugün İstanbul'da hava oldukça güzel ve güneşli.
> Yarın öğleden sonra saat üçte toplantımız var, lütfen zamanında gelin.
> Şirketimizin çeyreklik büyüme oranı yüzde on ikiye yükseldi, bu gerçekten
> önemli bir başarı."

| Model | Transkript |
|---|---|
| small | "Merhaba. Bugün İstanbul'da hava oldukça güzel ve güneşli. Yarın öğleden sonra saat **üçte** toplantımız var. Lütfen zamanında gelin. Şirketimizin çeyreklik büyüme oranı **yüzde on ikiye** yükseldi. Bu gerçekten önemli bir başarı." |
| large-v3-turbo | "Merhaba, bugün İstanbul'da hava oldukça güzel ve güneşli. Yarın öğleden sonra saat **3'te** toplantımız var. Lütfen zamanında gelin. Şirketimizin çeyreklik büyüme oranı **%12'ye** yükseldi. Bu gerçekten önemli bir başarı." |

**Kelime/anlam hatası yok — ikisi de kaynak metni doğru anladı.** Tek somut
fark: `large-v3-turbo` sayıları rakama normalize ediyor ("saat üçte" →
"saat 3'te", "yüzde on ikiye" → "%12'ye"), `small` konuşmadaki gibi yazıyla
bırakıyor. Hangisi "daha doğru" tamamen kullanım amacına bağlı (yazılı rapor
için rakam biçimi daha okunaklı olabilir; birebir konuşma dökümü için yazıyla
biçim daha sadık). Noktalama da hafif farklı (`large-v3-turbo` kaynaktaki ilk
virgülü koruyor, `small` noktaya çeviriyor) — anlamı etkilemiyor.

Bu, gTTS'in net/stüdyo-kalitesi TTS çıktısı olduğu, projenin asıl hedefi olan
gürültülü/düşük kaliteli gerçek kayıtları temsil etmediği unutulmamalı — bu
yüzden Türkçe için de "gürültülü/düşük kaliteli kayıtta model farkı" sorusu
hâlâ açık (bkz. Bulgu 3 "Değerlendirme").

### Doğruluk — daha zor/belirsiz bir İngilizce klip (`jfk.wav`, "she had your dark suit...")

Bu proje setindeki `test_fixtures/jfk.wav` (2.9s), "ask not..." alıntısından
FARKLI ve fonetik olarak daha belirsiz bir klasik konuşma-tanıma test
cümlesi ("she had your dark suit in greasy wash water all year" — doğru
metin). Burada, Bulgu 3'ün aksine, **model boyutu gerçekten fark yarattı**:

| Model | Transkript | Hata |
|---|---|---|
| tiny | "She had your dark suit in greasy wash **for** all year." | "water" → "for" |
| small | "She had **a duck** suit **and** greasy wash **for** all year." | "your dark" → "a duck", "in" → "and", "water" → "for" (3 hata — **tiny'den daha kötü**) |
| large-v3-turbo | "She had your dark suit **and** greasy wash water all year." | sadece "in" → "and" (1 hata, ama "water" doğru) |

**Bu tek örnekte `large-v3-turbo` en az hatalı, `small` ise `tiny`'den daha
kötü** — yani model boyutu ile doğruluk arasındaki ilişki monoton değil;
Bulgu 3'teki "temiz sesle model boyutu fark etmiyor" sonucu, kolay/net bir
kayıtla sınırlıydı. Daha belirsiz/fonetik olarak zor sesle gerçek bir fark
ortaya çıkabiliyor — ama tek bir 2.9s klip, genellemek için yeterli değil,
sadece "model boyutu her zaman farksızdır" iddiasını çürüten somut bir
karşı-örnek.

### Değerlendirme

`large-v3-turbo` ~3x daha yavaş ama bazı durumlarda (zor/belirsiz ses) daha
doğru olabiliyor; net/kolay seslerde fark yok. `WHISPER_MODEL_SIZE`
**değiştirilmedi** — env değişkeni olarak `small` varsayılanında kalıyor.
Gürültülü/düşük kaliteli gerçek kullanım senaryonuz hız toleranslıysa
(offline/toplu işleme gibi) `large-v3-turbo`'yu `.env`'de deneyip kendi
verinizle karşılaştırmanız önerilir.

Bu bulgu üzerine, `.env` genelinde sabit bir seçim yapmak yerine, **her
istekte** hız/doğruluk seçimi yapılabilmesi için `/api/transcribe`'a
`quality_mode` form alanı eklendi (`"standard"` → `WHISPER_MODEL_SIZE`,
`"precise"` → her zaman bu `large-v3-turbo` — bkz. README.md ve CLAUDE.md).
Yukarıdaki tüm ölçümler bu iki modun altyapısını doğrudan doğruluyor.

## Bulgu 5 — quality_mode: iki model aynı anda yüklenmeden per-istek seçim (2026-07-28)

`_get_local_whisper_model`/`_get_local_whisper_pipeline` artık `quality_mode`
anahtarlı bir dict'te (`_local_whisper_models`/`_local_whisper_pipelines`)
cache'leniyor — bir model sadece o `quality_mode` fiilen istendiğinde
yüklenir. Doğrulandı (mock'lu, gerçek model indirmeden — `test_local_mode.py`
`TestQualityMode`):

- Sadece `"standard"` istenirse `"precise"` (large-v3-turbo) hiç yüklenmez —
  gereksiz RAM kullanımı yok.
- Aynı `quality_mode`'a art arda gelen istekler cache'i kullanır — ikinci
  çağrıda `WhisperModel()` tekrar konstrüktle çağrılmaz.
- İki farklı `quality_mode` istenirse (bir sunucu ömrü boyunca hem standard
  hem precise talep edilirse) ikisi de ayrı ayrı cache'te kalır — bu durumda
  gerçekten iki model belleğe yüklenmiş olur (görev tanımının izin verdiği
  davranış: "gereksiz" olan aynı anda İKİSİNİ DE önceden yüklemek, talep
  edilmemiş bir modeli önceden yüklemek değil).

## Yapılan kod değişiklikleri

- `backend/server.py`: `_get_local_whisper_pipeline()` eklendi
  (`BatchedInferencePipeline`, model ile aynı ömürde cache'leniyor);
  `_transcribe_local()` artık `model.transcribe()` yerine
  `pipeline.transcribe(..., batch_size=WHISPER_BATCH_SIZE)` çağırıyor.
- `_local_cpu_threads()` eklendi (`os.sched_getaffinity(0)` tabanlı,
  Linux dışı sistemlerde `os.cpu_count()`'a düşer) — hem `WhisperModel`
  hem (varsa) diarization pipeline'ı bunu kullanıyor.
- `WHISPER_BATCH_SIZE` env değişkeni eklendi (varsayılan `8`).
- `WHISPER_MODEL_SIZE` **değiştirilmedi** — env değişkeni olarak kalıyor,
  varsayılan hâlâ `small`.
- Testler: `test_transcribe_local_calls_faster_whisper_and_shapes_output`
  artık `BatchedInferencePipeline` çağrısını doğruluyor; yeni
  `test_local_cpu_threads_uses_sched_affinity_not_cpu_count` regresyon testi
  eklendi. Tam paket: 21 passed, 4 skipped, 0 hata (bkz. `memory/PRD.md`
  changelog).
- **large-v3-turbo desteği için kod değişikliği GEREKMEDİ:** faster-whisper
  1.2.1 `available_models()` listesinde zaten var, `WHISPER_MODEL_SIZE`
  serbest metin (bir whitelist'e karşı doğrulanmıyor) — `.env`'de
  `WHISPER_MODEL_SIZE=large-v3-turbo` yazmak yeterli, gerçek sunucu üzerinden
  doğrulandı (bkz. Bulgu 4).

## Ölçüm scripti (tekrarlanabilirlik için)

```python
# .venv/bin/python bench_whisper.py {nonbatched|batched} <model_size> <cpu_threads> [batch_size]
# taskset -c 0-3 ile çalıştırılarak 4 çekirdekli VPS simüle edildi.
# BENCH_AUDIO / BENCH_LANGUAGE env değişkenleriyle farklı dosya/dil test edilebilir
# (örn. BENCH_LANGUAGE=tr Türkçe bir örnekle karşılaştırma için).
import os, resource, time, sys, json
from faster_whisper import WhisperModel, BatchedInferencePipeline

AUDIO = os.environ.get("BENCH_AUDIO", "test_fixtures/jfk.flac")
LANGUAGE = os.environ.get("BENCH_LANGUAGE", "en")

def cpu_time():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime

def run(label, fn):
    t0, c0 = time.perf_counter(), cpu_time()
    text = fn()
    wall = time.perf_counter() - t0
    cpu = cpu_time() - c0
    print(json.dumps({"label": label, "wall_s": round(wall, 3),
                       "cores_used": round(cpu / wall, 2) if wall else 0,
                       "text": text}, ensure_ascii=False))

mode = sys.argv[1]
if mode == "nonbatched":
    model_size, cpu_threads = sys.argv[2], int(sys.argv[3])
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
    run(f"nonbatched/{model_size}", lambda: " ".join(
        s.text.strip() for s in model.transcribe(AUDIO, language=LANGUAGE, vad_filter=True)[0]))
else:
    model_size, cpu_threads, batch_size = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
    pipeline = BatchedInferencePipeline(model=model)
    run(f"batched/{model_size}/batch_size={batch_size}", lambda: " ".join(
        s.text.strip() for s in pipeline.transcribe(
            AUDIO, language=LANGUAGE, vad_filter=True, batch_size=batch_size)[0]))
```
