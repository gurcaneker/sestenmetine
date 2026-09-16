# CLAUDE.md — SesteŞmetine Projesi

## Proje Özeti
Ses dosyalarını OpenAI Whisper ile metne döken, opsiyonel olarak Claude ile
konuşmacı ayrımı (diarization) yapan tek endpoint'lik bir transkripsiyon servisi.

**Şu an durumu:** Emergent AI-agent platformundan çıkmış, orchestrator + alt
ajan modeliyle (security → cleanup → consistency → test → infra → docs)
production-ready hale getirilmiş bir MVP. Auth, rate limiting, Docker deploy,
CI ve test kapsamı artık var — kalan açık noktalar için aşağıdaki "Bilinen
Kritik Sorunlar" listesine bakın. Tam değişiklik günlüğü:
`memory/PRD.md` "Profesyonelleştirme Geçmişi".

**Hedef:** Bu projeyi kademeli olarak production-ready, profesyonel bir
platforma dönüştürmek. Orchestrator ajan (proje sahibiyle birlikte planlama
yapan) ve alt ajanlar (VS Code içinde Claude Code ile çalışan, görev bazlı)
ile ilerliyoruz.

## Mevcut Mimari

```
sestenmetine/
├── backend/              FastAPI backend
│   ├── server.py         Tüm iş mantığı (TEK DOSYA — auth+rate limit dahil büyüdü)
│   ├── requirements.txt
│   ├── Dockerfile        Python 3.11-slim + ffmpeg, --workers 1 (bkz. SECURITY_NOTES.md)
│   ├── .env.example
│   ├── pytest.ini
│   └── tests/backend_test.py, tests/test_local_mode.py, tests/test_media_validation.py
├── frontend/              React 19 (CRA + craco)
│   ├── src/pages/Transcriber.jsx        Uygulamanın tüm mantığı (TEK BİLEŞEN)
│   ├── src/pages/Transcriber.test.jsx   Jest + React Testing Library
│   ├── src/components/ui/               shadcn/ui bileşenleri
│   ├── src/hooks/, src/lib/, src/constants/
│   ├── Dockerfile         Multi-stage: build (Node 22) + serve (Nginx)
│   ├── nginx.conf         /api reverse proxy → backend
│   ├── .env.example
│   └── package.json
├── docker-compose.yml     backend + frontend (MongoDB servisi YOK — kaldırıldı)
├── .env.example           docker-compose için (root — backend/frontend'inkinden ayrı)
├── .github/workflows/ci.yml   Opsiyonel CI: backend pytest + frontend yarn test
├── memory/PRD.md          Ürün gereksinim dokümanı + değişiklik günlüğü (en değerli dokümantasyon)
├── SECURITY_NOTES.md      Auth/rate-limit değerlendirmesi + implementasyon detayı
├── BENCHMARK.md           Local mode faster-whisper performans/model boyutu ölçümleri
├── design_guidelines.json Tasarım sistemi (Swiss/High-Contrast, Klein blue accent)
├── test_fixtures/         Örnek ses dosyaları
├── .emergent/             Emergent platformuna özel dosyalar (artık bağımlılık yok, referans)
└── README.md              Kurulum, mimari, test, API dokümantasyonu
```

- **Backend:** FastAPI 0.110 + uvicorn, pydub (ffmpeg), emergentintegrations
  (Whisper + Claude wrapper), slowapi (rate limiting), pytest + pytest-xdist.
  `TRANSCRIPTION_BACKEND=local` (opsiyonel, default `api`) ile faster-whisper
  kullanan tamamen yerel/offline bir mod da var — `EMERGENT_LLM_KEY`
  gerektirmez. pyannote.audio ile diarization kodu da mevcut ama **şu an
  devre dışı** (bkz. aşağıdaki "İş akışı" notu); `HF_TOKEN` fail-fast kontrolü
  bilinçli olarak kaldırılmadı. Ağır bağımlılıklar
  (`torch` dahil) `server.py` içinde lazy-import edilir, "api" modunu
  etkilemez. Bkz. README.md "Local mode ile çalıştırma".
- **Frontend:** React 19 + react-router-dom 7, shadcn/ui, Tailwind, framer-motion,
  axios, react-hook-form + zod, sonner
- **Veritabanı:** Yok. MongoDB tamamen kaldırıldı (cleanup-agent, 2026-07-23) —
  hiç CRUD/model kullanılmıyordu. Yeniden gerekirse (örn. kayıt geçmişi
  özelliği, P2 backlog) `memory/PRD.md`'de gerekçelendirilip eklenmeli.
- **Auth:** `X-API-Key` header + `POST /api/transcribe` için IP başına
  5/dakika rate limiting (slowapi, in-memory — tek worker/instance ile
  sınırlı, bkz. `SECURITY_NOTES.md`). JWT/çok-kullanıcılı sistem YOK (bilinçli).
- **Deploy:** Docker + Docker Compose (`backend/Dockerfile`,
  `frontend/Dockerfile` + Nginx reverse proxy, kök `docker-compose.yml`) ve
  opsiyonel GitHub Actions CI (`.github/workflows/ci.yml`). Çalıştırmak için:
  `cp .env.example .env` (kökte, doldurun) → `docker compose up --build`.
  `.emergent/emergent.yml` artık sadece geçmişten kalma referans, bir
  bağımlılık değil.

## API Endpoint'leri (/api prefix)

| Method | Path | Açıklama |
|---|---|---|
| GET | /api/ | Karşılama mesajı |
| GET | /api/health | Sağlık kontrolü |
| POST | /api/transcribe | Ana iş: dosya yükle → transkribe et |

`/transcribe`, `X-API-Key` header gerektirir (401 eşleşmezse) ve IP başına
5/dakika ile sınırlıdır (429 aşılırsa); `/` ve `/health` korumasız kalır.

İş akışı (`TRANSCRIPTION_BACKEND=api`, varsayılan): `transcribe_audio()` →
format/boyut doğrula → `_verify_media_stream()` (uzantıdan bağımsız, gerçek
içerik kontrolü — hem api hem local mode'da çalışır, bkz. aşağıdaki "Format
genişletme" notu) → `_prepare_chunks()` (mono/16kHz downsample, ≤20MB
parçalara böl) → Whisper'a `response_format=verbose_json` +
`timestamp_granularities=["word"]` ile gönder (kelime zaman damgaları —
neden segment değil kelime seviyesi için bkz. aşağıdaki "Duraklama-tabanlı
satır kırma" notu), `_format_transcript_with_pauses()` ile satırlara böl,
birleştir → `_diarize_with_claude()` → Whisper çıktısını claude-sonnet-4-6'ya
gönderip konuşmacı ayrımı yaptır (hata durumunda sessizce None dönüyor).

İş akışı (`TRANSCRIPTION_BACKEND=local`): aynı format/boyut doğrulaması →
`_transcribe_local()` (faster-whisper `BatchedInferencePipeline`,
`vad_filter=True` + `batch_size=WHISPER_BATCH_SIZE` + `cpu_threads=
_local_cpu_threads()` — `os.sched_getaffinity(0)` tabanlı, cgroup/container-
farkında — + `word_timestamps=True`, segment+kelime+timestamp'li; bkz.
`BENCHMARK.md`) → `diarized_text`/`speaker_timeline` her zaman `null` döner
— **diarization opt-in** (`enable_diarization=true` gerekir, bkz. aşağıdaki
madde; varsayılan `false`, performans önceliği korunuyor). API mode'da da
aynı şekilde opt-in (`_diarize_with_claude()`), varsayılan kapalı.

`/api/transcribe`'ın `quality_mode` form alanı (`"standard"` varsayılan,
veya `"precise"`) sadece local mode'u etkiler: `"standard"` → `WHISPER_MODEL_SIZE`,
`"precise"` → her zaman `large-v3-turbo` (env'den bağımsız, sabit). Her iki
model de ayrı ayrı, sadece talep edildiklerinde belleğe yüklenip cache'lenir
(`_local_whisper_models`/`_local_whisper_pipelines`, `quality_mode` anahtarlı
dict) — bir mod hiç istenmediyse hiç yüklenmez, aynı modda art arda gelen
istekler yeniden yükleme maliyeti ödemez. Detay ve doğruluk/hız karşılaştırması:
`BENCHMARK.md` "Bulgu 4".

`enable_diarization` form alanı (bool, varsayılan `false`) diarization'ı
opt-in yapar: `true` iken `diarized_text` (eski "1. kişi:" formatı, her iki
modda) VE local mode'da ayrıca `speaker_timeline` (yeni, 0-tabanlı
"Speaker {n}\n{start:.2f}\n{text}\n{end:.2f}" formatı, `_format_speaker_
timeline()`) doldurulur. `speaker_timeline` api mode'da her zaman `null` —
`_diarize_with_claude()`'ın gerçek zaman bilgisine erişimi yok. Varsayılan
`false` iken davranış tamamen eskisi gibi (performans maliyeti yok).

## Bilinen Kritik Sorunlar

Orijinal 9 maddelik liste (security → docs ajan sırasıyla) — durum güncellendi:

1. ✅ **Çözüldü — CORS güvenlik açığı** (security-agent): `allow_origins='*'`
   kaldırıldı, `CORS_ORIGINS` env değişkeninden liste okunuyor, default
   localhost'a sınırlı.
2. ✅ **Çözüldü — env değişkeni çökmesi** (security-agent): `os.environ.get()`
   + eksik değişkeni adıyla belirten net `RuntimeError`.
3. ✅ **Çözüldü — dosya boyutu limiti tutarsızlığı** (consistency-agent): tek
   kaynak `MAX_UPLOAD_SIZE` (500MB), frontend/backend/PRD senkron.
4. ✅ **OGG çözüldü, FLAC bilinçli olarak hâlâ kapalı (2026-07-28):** Bu madde
   önceden "FLAC/OGG ikisi de kapalı" idi (consistency-agent, Seçenek A —
   net 400, 500 yerine). Artık **.ogg `ALLOWED_EXTS`'te** — infra-agent'ın
   Docker build'inde ffmpeg'in kurulu olduğunu doğrulaması VE yeni
   `_verify_media_stream()` (ffprobe/PyAV ile gerçek stream içeriği kontrolü,
   bkz. aşağıdaki "Format genişletme" notu) bu maddeyi eskiden bloke eden iki
   şeyi de kapattı. **FLAC hâlâ bilinçli olarak dışarıda** (Seçenek B —
   server-side transcoding — kod olarak hazır ve lokal test edilmiş ama
   ayrıca ele alınmadı; bu FLAC kararı bu değişiklikle yeniden gözden
   geçirilmedi, kasıtlı olarak öyle bırakıldı).
5. ✅ **Çözüldü/düzeltildi — sessiz hata yutma:** `_diarize_with_claude` zaten
   `logger.exception` ile logluyormuş; bu maddenin orijinal tespiti güncel
   değilmiş (security-agent doğrulaması).
6. ✅ **Çözüldü — kullanılmayan bağımlılıklar** (cleanup-agent): stripe,
   python-jose, PyJWT, passlib, bcrypt, google-generativeai, google-genai,
   boto3 kaldırıldı (+ MongoDB kaldırılınca motor/pymongo/dnspython da).
7. ✅ **Çözüldü — auth/yetkilendirme yok:** `X-API-Key` header (401 eşleşmezse)
   + `POST /api/transcribe` için IP başına 5/dakika rate limiting (429).
   JWT/çok-kullanıcılı sistem bilinçli olarak YOK — bkz. `SECURITY_NOTES.md`.
8. ✅ **Çözüldü — test kapsamı** (test-agent): backend testleri auth/rate-limit
   senaryolarıyla genişledi; frontend'de sıfırdan Jest + RTL kuruldu
   (`Transcriber.test.jsx`).
9. ✅ **Çözüldü — kurulum dokümantasyonu yok** (docs-agent): `README.md` dolu,
   `backend/`, `frontend/` ve kök `.env.example` dosyaları var.

**Yeni, bu süreçte ortaya çıkan açık noktalar:**
- **Rate limit ölçeklenmiyor:** slowapi'nin in-memory storage'ı tek
  worker/instance için doğru; birden fazla worker/container'a çıkılırsa
  gerçek limit worker sayısıyla çarpılır — Redis storage backend'ine
  geçilmeden `--workers 1` üzerine çıkılmamalı (bkz. `SECURITY_NOTES.md`,
  `backend/Dockerfile` yorumu).
- **Docker build ağ doğrulaması eksik:** infra-agent'ın çalıştığı sandbox'ta
  `docker compose build`'ın varsayılan ağı DNS çözemiyordu, `docker build
  --network host` ile aşıldı ve tüm stack (health-check + auth 401/200,
  nginx reverse-proxy dahil) bu şekilde doğrulandı. Normal bir geliştirme
  makinesinde/CI runner'ında bu kısıtlama olmaması beklenir ama **gerçek bir
  CI/production ortamında `docker compose up --build` henüz ayrıca
  doğrulanmadı** — infra-agent görevine bakan biri bunu ilk fırsatta
  gerçek bir ortamda teyit etmeli.
- **Local mode (faster-whisper + pyannote.audio) eklendi, gerçek bir HF
  token'la uçtan uca doğrulandı** — `diarized_text` gerçekten "1. kişi /
  2. kişi" formatında dolu döndüğü dahil (bkz. `memory/PRD.md` changelog).
  pyannote.audio 4.x ile ilgili dört gerçek uyumsuzluk bulunup düzeltildi:
  `from_pretrained()`'ın kwarg'ı `use_auth_token`→`token`; `speaker-diarization-3.1`
  ayrıca gated bir modele (`speaker-diarization-community-1`) bağımlı, o da
  ayrıca onaylanmalı (README.md "Local mode" adım 3); dosya-yolu tabanlı okuma
  `torchcodec`/sistem-ffmpeg gerektiriyor — `_decode_waveform_for_pyannote`
  ile `av` üzerinden kendi decode edip pyannote'a waveform tensor'ü olarak
  veriliyor (Docker image'ında ffmpeg zaten kurulu olduğu için orada bu
  sorun yaşanmaz, ama kod artık ikisinde de çalışıyor); pipeline artık düz
  `Annotation` değil `.speaker_diarization` alanlı bir `DiarizeOutput` dönüyor.
- **⚠️ Docker image'ı artık local-mode bağımlılıklarını da (torch dahil,
  ~GB seviyesinde) kuruyor — API-only deploy'lar için gereksiz şişkinlik:**
  `faster-whisper`/`pyannote.audio` `requirements.txt`'te koşulsuz listeli
  (server.py'de lazy-import ediliyor olması sadece Python import'unu
  etkiler); `backend/Dockerfile`'ın `pip install -r requirements.rest.txt`
  adımı bunları da kurar, `TRANSCRIPTION_BACKEND=api` ile hiç kullanılmasa
  bile. infra-agent'ın Dockerfile'ı local mode'dan ÖNCE yazıldığı için bunu
  hesaba katmadı. Düzeltilmedi — olası çözüm: local-mode paketlerini ayrı
  bir `requirements-local.txt`'e taşıyıp Docker build'e opsiyonel bir
  `ARG`/build-stage ile bağlamak (yapılırsa `docker-compose.yml` ve
  `backend/Dockerfile` güncellenmeli).
- **Local mode'da diarization devre dışı bırakıldı (2026-07-28, sonradan
  opt-in'e çevrildi — bkz. aşağıdaki "enable_diarization" girdisi):**
  `_diarize_local()`/`_align_and_format_diarization()` uçtan uca doğrulanmış
  ve çalışır durumdaydı, ama hedef VPS'te GPU olmadığı için pyannote.audio'nun
  Whisper'ın üzerine eklediği CPU süresi kabul edilemez bulundu — bu proje
  local mode'u önceliği doğruluk/hız olan bir transkripsiyon aracı olarak
  kullanıyor, diarization olmadan da hedefine ulaşıyor. `transcribe_audio()`
  içinde `_diarize_local` çağrısı yorum satırına alındı, `diarized_text` local
  modda her zaman `null` döner (frontend zaten `Boolean(diarized_text)` ile
  kontrol ediyor, ek değişiklik gerekmedi). `_transcribe_local()`'a doğruluğu
  koruyan/artıran iki ayar eklendi: `vad_filter=True` (sessizlik atlama) ve
  `cpu_threads=os.cpu_count()`; `beam_size`'a dokunulmadı (doğruluk/hız
  trade-off'u, doğruluk önceliklendirildi). Yeniden açmak için: server.py'de
  ilgili yorum satırındaki bloğun yorumunu kaldırın — kod ve testler
  (`test_diarize_local_calls_pyannote_with_token`) hâlâ mevcut ve çalışıyor.
  API mode (Claude ile diarization) hiç etkilenmedi.
- **Local mode performans optimizasyonu + model boyutu benchmark'ı
  (2026-07-28):** `_transcribe_local()` artık faster-whisper'ın
  `BatchedInferencePipeline`'ını kullanıyor (VAD segmentlerini toplu işler)
  — 4 çekirdekli bir VPS simülasyonunda (`taskset -c 0-3`) 7-8.5x hızlanma
  ölçüldü. Ayrıca gerçek bir bug bulunup düzeltildi: `cpu_threads=
  os.cpu_count()` host'un toplam çekirdek sayısını döndürüyor, cgroup/
  container/VPS CPU kısıtlamasını görmüyor — bu, gerçek limitten fazla
  thread açılmasına (oversubscription, "~117% CPU" belirtisiyle uyumlu) ve
  daha kötü performansa yol açıyordu; `_local_cpu_threads()`
  (`os.sched_getaffinity(0)`, cgroup/taskset-farkında) ile düzeltildi.
  `WHISPER_BATCH_SIZE` env değişkeni eklendi (varsayılan 8). Tam ölçüm
  metodolojisi, sayılar ve tiny/base/small model karşılaştırması:
  **`BENCHMARK.md`**. `WHISPER_MODEL_SIZE` bilinçli olarak env değişkeni
  olarak bırakıldı (kod içinde sabitlenmedi) — bu benchmark'ın temiz/tek
  konuşmacılı test verisinde model boyutunun kelime doğruluğuna ölçülebilir
  bir etkisi bulunamadı (gerçek hedef kullanım senaryosu — gürültülü/düşük
  kaliteli kayıt — için ayrıca test edilmesi öneriliyor, bkz. BENCHMARK.md
  "Değerlendirme").
- **Format genişletme + gerçek içerik doğrulaması (2026-07-28):** `ALLOWED_EXTS`
  genişletildi — `.ogg` yeniden eklendi (yukarıdaki madde 4'e bkz.), yeni bir
  `DVR_EXTS = {"dav"}` seti eklendi (Dahua ve benzeri DVR/güvenlik kamerası
  kayıtları — H.264 video + G.711/G.726 ses, best-effort: standart bir
  konteyner değil, ffmpeg/libav çoğunlukla ama garanti olmadan decode edebilir).
  `flac` hâlâ dışarıda (madde 4). Yeni `_verify_media_stream()`, her
  `/api/transcribe` isteğinde (TRANSCRIPTION_BACKEND'den bağımsız, hem api hem
  local mode'da) uzantıya güvenmek yerine dosyanın gerçekten decode edilebilir
  bir ses stream'i içerip içermediğini kontrol ediyor — `ffprobe` CLI'ı
  yerine `PyAV` (`av`) kullanıyor (aynı libav altyapısı, ama sistemde ffmpeg/
  ffprobe binary'si gerektirmiyor — `_decode_waveform_for_pyannote`'la aynı
  gerekçe). `av` kurulu değilse (teoride "api"-only bir deploy'da olabilir,
  ama şu an Docker image'ı zaten kuruyor — madde 3'teki bloat notuna bkz.)
  sessizce eski uzantı-bazlı davranışa düşüyor, hard-fail olmuyor. `.dav`
  içerik doğrulaması başarısız olursa jenerik "desteklenmiyor" yerine net,
  actionable bir 400 dönüyor ("VLC ile dönüştürüp tekrar deneyin"). Test:
  `backend/tests/test_media_validation.py` (yeni dosya) — gerçek bir PyAV'la
  sentezlenmiş minimal Ogg/Vorbis dosyasıyla kabul senaryosu dahil (gerçek
  bir `.dav` örneği bulunamadı/pratik değildi — o senaryo bozuk/sahte byte'larla
  test edildi, bkz. dosyanın modül docstring'i). Tam paket: 28 test geçti,
  4 skip, 0 hata.
- **large-v3-turbo benchmark'a eklendi (2026-07-28, kod değişikliği yok):**
  faster-whisper 1.2.1 `large-v3-turbo`'yu zaten tanıyor, `WHISPER_MODEL_SIZE`
  serbest metin olduğu için `.env`'de `WHISPER_MODEL_SIZE=large-v3-turbo`
  yazmak yeterli — gerçek sunucu üzerinden doğrulandı. `small`'a göre
  tutarlı şekilde ~3x daha yavaş; net/kolay bir kayıtta (`jfk.flac`, "ask
  not...") kelime doğruluğu farkı yok, ama daha zor/belirsiz bir klipte
  (`jfk.wav`, "she had your dark suit...") **`small`, `tiny`'den daha fazla
  hata yaptı, `large-v3-turbo` ise en az hatalıydı** — model boyutu/doğruluk
  ilişkisinin monoton olmadığına dair somut bir örnek. Ayrıca gerçek bir
  Türkçe örnekle (gTTS ile bu ölçüm için üretildi, projeye bağımlılık olarak
  eklenmedi) test edildi: kelime/anlam hatası yok, tek fark `large-v3-turbo`'nun
  sayıları rakama normalize etmesi ("saat üçte"→"saat 3'te"). `WHISPER_MODEL_SIZE`
  **değiştirilmedi** — env değişkeni, varsayılan hâlâ `small`. Tam detay:
  `BENCHMARK.md` Bulgu 4.
- **Per-istek quality_mode seçimi eklendi (2026-07-28):** `/api/transcribe`'a
  yeni bir opsiyonel form alanı — `quality_mode` (`"standard"` varsayılan,
  `"precise"`). Local mode'da `"standard"` → `WHISPER_MODEL_SIZE`, `"precise"`
  → her zaman `large-v3-turbo` (env'den bağımsız). Geçersiz bir değer net bir
  400 ile reddediliyor. Model/pipeline cache'i `quality_mode` anahtarlı bir
  dict'e taşındı (`_local_whisper_models`/`_local_whisper_pipelines`) — iki
  model de aynı anda belleğe yüklenmiyor, sadece fiilen talep edilen mod
  yükleniyor, aynı moddaki art arda istekler cache'i kullanıyor. Frontend'e
  "Hızlı (standart)" / "Hassas (yavaş, gürültülü/zor kayıtlar için)" iki
  buton eklendi (varsayılan Hızlı), BENCHMARK.md Bulgu 4'ü özetleyen kısa bir
  açıklama metniyle. api mode bu alandan etkilenmiyor (yok sayılıyor).
  Test: `test_local_mode.py`'ye yeni bir `TestQualityMode` sınıfı — model
  boyutu çözümlemesi, cache'in mod başına ayrı tutulduğu, bir modun
  diğerini asla yüklemediği, endpoint'in `quality_mode`'u doğru forward
  ettiği ve geçersiz değeri reddettiği, hepsi mock'lu (gerçek model indirmeden).
- **Duraklama-tabanlı satır kırma eklendi (2026-07-28):** `text` alanı artık
  düz tek paragraf değil — iki konuşma birimi arasındaki boşluk
  `PAUSE_THRESHOLD_SECONDS`'ı (1.3s, kod içinde sabit, env değil) aştığında
  `\n` ile satırlara bölünüyor. Bu **diarization DEĞİL** — konuşmacı etiketi
  ("1. kişi" vb.) eklenmiyor, sadece okunabilirlik için satır kırma;
  `diarized_text` alanına hiç dokunulmadı. Yeni `_format_transcript_with_
  pauses()` fonksiyonu hem local hem api mode'da kullanılıyor.
  **Gerçek, test sırasında bulunan bir sorun:** ilk tasarım Whisper'ın kendi
  segment (cümle/ifade seviyesi) sınırlarını kullanıyordu, ama gerçek testte
  `BatchedInferencePipeline`'ın VAD ile ayırdığı konuşma bloklarını tek bir
  kaba `Segment`'te birleştirebildiği görüldü — sentetik 3 saniyelik bir
  sessizlik içeren bir klipte TÜM klip tek bir segment olarak döndü, boşluk
  segment sınırlarında hiç görünmedi. Çözüm: `word_timestamps=True` ile
  **kelime seviyesi** zaman damgaları kullanılıyor (segment değil) — aynı
  test klibinde kelimeler arasındaki 3s+ boşluk doğru şekilde tespit edildi.
  API mode'da da tutarlılık için aynı yaklaşım kullanıldı
  (`timestamp_granularities=["word"]`, `response_format=verbose_json`) —
  OpenAI'nin gerçek API'sinde aynı sorunun olup olmadığı bu dev ortamında
  test edilemedi (`EMERGENT_LLM_KEY` yok), bu yüzden varsayımda bulunmak
  yerine iki modda da aynı, test edilmiş granülariteyi kullanmak tercih
  edildi. `whisper_segments` (diarization alignment için kullanılan, şu an
  devre dışı) değişmedi — hâlâ segment seviyesinde, ayrı tutuldu. Gerçek
  sunucu üzerinden hem duraklamalı hem duraklamasız gerçek ses dosyalarıyla
  doğrulandı. Test: `test_local_mode.py`'ye `TestFormatTranscriptWithPauses`
  (saf mantık, 7 test) + `TestNormalizeOpenAISegments` (4 test) + bir
  entegrasyon testi eklendi. Tam paket: 49 test geçti, 4 skip, 0 hata.
  Detay: README.md.
- **Diarization opt-in olarak yeniden etkinleştirildi, yeni zaman damgalı
  format ile (2026-07-28):** `/api/transcribe`'a yeni bir opsiyonel form
  alanı — `enable_diarization` (bool, varsayılan `false`). `true` olduğunda:
  local mode'da `_diarize_local()`, api mode'da `_diarize_with_claude()`
  çağrılır (**ikisi de değişmeden** — sadece çağrı koşullu hale geldi,
  görev tanımının açık kısıtı). `false` (varsayılan) iken davranış tamamen
  eskisi gibi — performans maliyeti sıfır, önceki "diarization tamamen
  kapalı" kararı geri alınmadı, sadece opt-in'e çevrildi.
  - **Yeni format, sadece local mode'da:** `_format_speaker_timeline()`
    (yeni fonksiyon, dokunulmamış `_align_and_format_diarization`'ın
    yanında) pyannote'un turn'lerini (`diar_segments`) doğrudan kullanarak
    `Speaker {n}\n{start:.2f}\n{text}\n{end:.2f}` bloklarını üretir —
    speaker numaraları **0-tabanlı** ("Speaker 0", eski "1. kişi" formatının
    1-tabanlı olmasından farklı). Turn-driven (segment-merge değil): aynı
    konuşmacının iki AYRI pyannote turn'ü (arada duraklama varsa) tek bloğa
    birleştirilmez, ayrı ayrı kalır — göreve verilen örnek çıktı formatı
    tam olarak bunu gösteriyor. Yeni `speaker_timeline` alanında dönüyor,
    **eski `diarized_text` alanına hiç dokunulmadı** (geriye dönük uyumluluk,
    aynı anda ikisi de doldurulabilir).
  - **API mode'da `speaker_timeline` bilinçli olarak her zaman `null`:**
    `_diarize_with_claude()` sadece nihai transkript METNİNİ görüyor, asla
    gerçek ses zaman bilgisine erişmiyor — bir LLM'in metinden gerçek
    saniye-hassasiyetinde zaman damgası üretmesinin dürüst bir yolu yok.
    Yeni zaman damgalı format gerçek zaman verisi gerektiriyor (pyannote
    turn'leri + Whisper segment timestamp'leri), bu sadece local mode'da
    var. `diarized_text` (eski format) api mode'da hâlâ `enable_diarization=
    true` ile dolduruluyor, sadece `speaker_timeline` boş kalıyor.
  - Gerçek sunucu üzerinden, gerçek bir `HF_TOKEN` ile uçtan uca doğrulandı
    (pyannote pipeline'ı gerçekten çalıştı, tek konuşmacılı bir klipte
    beklenen şekilde her iki alan da `null` döndü — soft-fail, çökme yok).
  - Frontend (`Transcriber.jsx`): "Konuşmacıları ayır (yavaş)" checkbox'ı
    eklendi (varsayılan kapalı, quality-mode panelinin altında), `enable_
    diarization` form alanına ekleniyor. `speaker_timeline` doluysa ana
    transkript metninin altında ayrı bir "Konuşmacı Zaman Çizelgesi"
    bölümünde yeni `SpeakerTimeline` bileşeniyle gösteriliyor (eski
    `DiarizedText` bileşeninden ayrı, ona hiç dokunulmadı).
  - Test: `test_local_mode.py`'ye yeni `TestFormatSpeakerTimeline` (6 test,
    göreve verilen örnekle birebir eşleşen bir test dahil) ve
    `TestLocalModeDiarizationOptIn` (eski `TestLocalModeDiarizationDisabled`
    yerine geçti — varsayılan kapalı, açıkken her iki alanın da dolduğu,
    diarization hatasının soft-fail olduğu) eklendi. Tam paket: 57 test
    geçti, 4 skip, 0 hata.
- **🔴 REGRESYON + DÜZELTME — `speaker_timeline` gerçek çok-konuşmacılı
  ses dosyasında tüm transkripti her bloğa tekrarlıyordu (2026-09-16):**
  Yukarıdaki maddenin "gerçek sunucu üzerinden uçtan uca doğrulandı" notu
  **yanıltıcıydı** — o doğrulama tek-konuşmacılı bir kliple yapılmıştı,
  yani `_align_and_format_diarization`/`_format_speaker_timeline`'ın
  gerçek overlap-eşleme mantığı (2+ konuşmacı gerektiren dal) hiç
  çalıştırılmadan "soft-fail, `null` döndü" olarak yeşile boyanmıştı. Gerçek
  çok-konuşmacılı bir kayıtta her "Speaker N" bloğu SADECE kendi turn'üne
  ait metin yerine 17 cümlelik transkriptin TAMAMINI tekrar tekrar
  içeriyordu ve son bloklarda başlangıç/bitiş zaman damgaları görünüşte
  ters dönmüş gibiydi (örn. "17.88s–13.62s").
  - **Kök neden:** `_transcribe_local()`, diarization hizalaması için
    `_align_and_format_diarization`/`_format_speaker_timeline`'a Whisper'ın
    kendi KABA (cümle/ifade seviyesi) `whisper_segments` listesini
    veriyordu — tam olarak "Duraklama-tabanlı satır kırma" maddesinde
    zaten belgelenmiş, `BatchedInferencePipeline`'ın VAD ile ayrılmış
    konuşma bloklarını tek bir kaba `Segment`'e birleştirebildiği (gerçek
    testte doğrulanmış) sorun. Bir kaba segment tüm klibi (hatta tüm
    konuşmayı) kapsayınca, HER pyannote turn'ü o segmentle overlap ediyor,
    "any overlap counts" eşleştirmesi her turn'e transkriptin tamamını
    veriyordu. Görünürdeki "ters zaman damgası" ayrı bir hata değildi —
    bunun bir yan etkisiydi: frontend'in `SpeakerTimeline` bileşeni sabit
    4-satır varsayımıyla parse ediyordu, gövde metni (`body`) beklenmedik
    şekilde çok satırlı olduğunda (veya format kaymasında) sonraki blokların
    start/end değerleri kayıyor, komşu bloklardan değer sızıyordu.
  - **Düzeltme:** `_transcribe_local()` artık diarization için KELİME
    seviyesi zaman damgalarını (`words`, zaten `word_timestamps=True` ile
    hesaplanıyordu ama sadece duraklama tespiti için kullanılıyordu) döndürüyor
    — `return raw_text, (words or whisper_segments)` (kaba segment'e düşme
    sadece hiç kelime zaman damgası yoksa, örn. sessiz ses). Kelimeler
    ~0.1-0.5s genişliğinde olduğu için overlap eşleştirmesi artık gerçekten
    konuşmacılar arasında ayrım yapabiliyor. `_align_and_format_diarization`
    ve `_format_speaker_timeline`'ın parametre adları (`whisper_words`) ve
    docstring'leri bu beklentiyi netleştirecek şekilde güncellendi — ikisi
    de artık segment değil kelime listesi bekliyor (fonksiyonların kendi iç
    mantığı değişmedi, sadece hangi granülerlikte veri aldıkları).
  - **Testin neden yakalayamadığı + düzeltme:** `TestAlignAndFormatDiarization`/
    `TestFormatSpeakerTimeline`'daki mevcut sentetik testler zaten kelime/
    ifade-boyutunda "segment"ler kullanıyordu (örn. 3-4 kelimelik ayrı
    segmentler) — gerçek `_transcribe_local`'ın üretebileceği TEK KABA,
    çok-turn'lü bir segment senaryosunu hiç simüle etmiyorlardı, ve gerçek
    e2e doğrulama da yanlışlıkla tek-konuşmacılı (dolayısıyla bu kod yolunu
    hiç çalıştırmayan) bir kliple yapılmıştı. Eklenen yeni testler: (1) her
    iki fonksiyona da ~16 turn'lük, hızlı dönüşümlü, gerçekçi kelime-seviyeli
    bir diyalog veren `test_many_short_alternating_turns_word_level` /
    `test_realistic_many_alternating_turns_word_level` — her bloğun SADECE
    kendi kelimelerini içerdiğini, başka turn'lerden veya tüm transkriptten
    kelime sızmadığını doğruluyor; (2) `_transcribe_local` seviyesinde
    `test_transcribe_local_returns_word_level_not_coarse_segments_for_diarization`
    — TEK bir kaba segment (gerçek bug koşulunu simüle eden) birden fazla
    gerçek kelime zaman damgası taşıdığında, dönen ikinci tuple elemanının
    kelime listesi olduğunu, kaba segment aralığı OLMADIĞINI doğrudan
    doğruluyor (asıl hatanın yaşandığı sınır — çağıran taraf). Frontend
    `Transcriber.jsx`'teki `SpeakerTimeline` parser'ı da savunma amaçlı
    sağlamlaştırıldı: artık sabit 4-satır adımı yerine "Speaker N" başlık
    satırı + ardından bir zaman damgası satırı arayıp, bir sonraki saf
    zaman damgası satırına kadar olan her şeyi gövde olarak alıyor — gövde
    metninde beklenmedik bir `\n` olsa bile sonraki blokların değerleri
    artık kaymıyor. Tam paket: 49 test geçti (backend + local_mode +
    media_validation), 2 skip, 0 hata (bkz. `backend_test.py` ayrıca canlı
    sunucu + `REACT_APP_BACKEND_URL` gerektirir, bu regresyonla ilgisiz).
  - **Ders/kural:** Bir e2e doğrulama "soft-fail, null döndü" ile geçtiğinde,
    bunun testin gerçekten ilgili kod yolunu (burada: 2+ konuşmacı dalını)
    çalıştırdığı anlamına GELMEDİĞİNİ unutma — özellikle diarization/çok-
    konuşmacı özellikleri için doğrulama en az 2 farklı konuşmacı içeren
    gerçek veriyle yapılmalı, tek-konuşmacılı bir klip bu dalı hiç
    tetiklemez. Ayrıca: birim testleri gerçek modelin/pipeline'ın
    üretebileceği en kötü/en kaba veri şeklini (burada: VAD-merge'lenmiş tek
    dev segment) simüle etmezse, "segment" ve "kelime" gibi farklı
    granülerlik seviyeleri arasındaki bir karışıklık sentetik testte hiç
    görünmeyebilir.

## Sabit Kurallar (Claude Code her zaman uymalı)

- `pytest.ini` içindeki `addopts`'a **DOKUNMA** — dosyada açık uyarı var:
  "AGENT: do NOT modify addopts" (`-n 2 --dist loadscope`).
- Yeni endpoint/route eklerken mevcut `/api` prefix konvansiyonuna uy.
- MongoDB kaldırıldı (yukarıdaki "Mevcut Mimari" notuna bakın) — yeniden
  eklenecekse karar önce `memory/PRD.md`'de gerekçelendirilsin, sessizce
  eklenmesin.
- Her değişiklik sonrası `backend/tests/backend_test.py`,
  `backend/tests/test_local_mode.py` VE `backend/tests/test_media_validation.py`
  çalıştırılıp doğrulansın (`pytest tests/` üçünü birden çalıştırır).
- Gerçek Whisper/Claude API çağrısı gerektiren testler var — bu testleri kırmadan
  önce PRD.md'deki test senaryolarını oku.
- Kod tabanı şu an "tek dosya, tek bileşen" yapısında — refactor yaparken
  fonksiyonelliği koruyarak kademeli böl, tek seferde büyük bir "big bang"
  yeniden yazım yapma.

## Referans Dokümanlar

- `memory/PRD.md` — ürün gereksinimleri, persona'lar, backlog (P1: zaman damgalı
  transkripsiyon/SRT-VTT; P2: FLAC/OGG server-side transcoding [kod hazır,
  altyapı doğrulaması bekliyor], dil algılama, kayıt geçmişi, mikrofon kaydı)
  ve "Profesyonelleştirme Geçmişi" (tüm alt ajanların değişiklik günlüğü).
- `SECURITY_NOTES.md` — auth/rate-limit risk değerlendirmesi + implementasyon
  detayı (API-key, slowapi, in-memory storage kısıtı).
- `README.md` — kurulum (lokal + Docker), test çalıştırma, API endpoint tablosu.
- `BENCHMARK.md` — local mode faster-whisper performans ölçümleri (batching,
  cpu_threads düzeltmesi) ve tiny/base/small model karşılaştırması.
- `design_guidelines.json` — tasarım sistemi tanımı.

## Çalışma Yöntemi

Bu proje bir **orchestrator + alt ajan** modeliyle geliştiriliyor:
- Orchestrator (proje sahibiyle birlikte, Claude.ai üzerinde) plan yapar,
  görevleri önceliklendirir, her alt ajan için görev tanımı üretir.
- Alt ajanlar (bu dosyayı okuyan Claude Code, VS Code içinde) görevleri sırayla,
  birbirine bağımlılık sırasına göre uygular: security → cleanup → consistency
  → test → infra → docs.
- Her alt ajan görevine başlamadan önce bu CLAUDE.md dosyasını ve ilgili
  `agents/*.md` görev dosyasını okumalı.
