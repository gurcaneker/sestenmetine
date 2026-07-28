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
parçalara böl) → Whisper'a gönder, birleştir → `_diarize_with_claude()` →
Whisper çıktısını claude-sonnet-4-6'ya gönderip konuşmacı ayrımı yaptır (hata
durumunda sessizce None dönüyor).

İş akışı (`TRANSCRIPTION_BACKEND=local`): aynı format/boyut doğrulaması →
`_transcribe_local()` (faster-whisper `BatchedInferencePipeline`,
`vad_filter=True` + `batch_size=WHISPER_BATCH_SIZE` + `cpu_threads=
_local_cpu_threads()` — `os.sched_getaffinity(0)` tabanlı, cgroup/container-
farkında —, segment+timestamp'li; bkz. `BENCHMARK.md`) → `diarized_text` her
zaman `null` döner. **Diarization (`_diarize_local()` + `_align_and_format_diarization()`)
şu an devre dışı** — hedef VPS'te (GPU yok) pyannote'un CPU maliyeti kabul
edilemez bulundu; kod silinmedi, `transcribe_audio()` içinde çağrı yorum
satırına alındı (bkz. kod yorumu ve README.md "Local mode ile çalıştırma"
— yeniden açma talimatı orada). API mode bundan etkilenmez.

`/api/transcribe`'ın `quality_mode` form alanı (`"standard"` varsayılan,
veya `"precise"`) sadece local mode'u etkiler: `"standard"` → `WHISPER_MODEL_SIZE`,
`"precise"` → her zaman `large-v3-turbo` (env'den bağımsız, sabit). Her iki
model de ayrı ayrı, sadece talep edildiklerinde belleğe yüklenip cache'lenir
(`_local_whisper_models`/`_local_whisper_pipelines`, `quality_mode` anahtarlı
dict) — bir mod hiç istenmediyse hiç yüklenmez, aynı modda art arda gelen
istekler yeniden yükleme maliyeti ödemez. Detay ve doğruluk/hız karşılaştırması:
`BENCHMARK.md` "Bulgu 4".

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
- **Local mode'da diarization devre dışı bırakıldı (2026-07-28):**
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
