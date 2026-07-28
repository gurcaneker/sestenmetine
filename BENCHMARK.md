# Local Mode Whisper Benchmark (2026-07-28)

Bu doküman, `TRANSCRIPTION_BACKEND=local` (`backend/server.py` →
`_transcribe_local`) için yapılan performans optimizasyonunun ve
tiny/base/small model karşılaştırmasının ölçüm sonuçlarını kaydeder. Amaç:
gerçek veriyle karar vermek, tahminle değil — `WHISPER_MODEL_SIZE` ve
`WHISPER_BATCH_SIZE` seçimi bu ölçümlere dayanıyor ama env değişkeni olarak
kalıyor (kod içinde sabitlenmedi), böylece kendi ses verinizle farklı
sonuç alırsanız `.env`'den değiştirebilirsiniz.

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

## Ölçüm scripti (tekrarlanabilirlik için)

```python
# .venv/bin/python bench_whisper.py {nonbatched|batched} <model_size> <cpu_threads> [batch_size]
# taskset -c 0-3 ile çalıştırılarak 4 çekirdekli VPS simüle edildi.
import os, resource, time, sys, json
from faster_whisper import WhisperModel, BatchedInferencePipeline

AUDIO = os.environ.get("BENCH_AUDIO", "test_fixtures/jfk.flac")

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
        s.text.strip() for s in model.transcribe(AUDIO, language="en", vad_filter=True)[0]))
else:
    model_size, cpu_threads, batch_size = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
    pipeline = BatchedInferencePipeline(model=model)
    run(f"batched/{model_size}/batch_size={batch_size}", lambda: " ".join(
        s.text.strip() for s in pipeline.transcribe(
            AUDIO, language="en", vad_filter=True, batch_size=batch_size)[0]))
```
