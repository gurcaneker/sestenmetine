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
│   └── tests/backend_test.py, tests/test_local_mode.py
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
├── design_guidelines.json Tasarım sistemi (Swiss/High-Contrast, Klein blue accent)
├── test_fixtures/         Örnek ses dosyaları
├── .emergent/             Emergent platformuna özel dosyalar (artık bağımlılık yok, referans)
└── README.md              Kurulum, mimari, test, API dokümantasyonu
```

- **Backend:** FastAPI 0.110 + uvicorn, pydub (ffmpeg), emergentintegrations
  (Whisper + Claude wrapper), slowapi (rate limiting), pytest + pytest-xdist.
  `TRANSCRIPTION_BACKEND=local` (opsiyonel, default `api`) ile faster-whisper
  + pyannote.audio kullanan tamamen yerel/offline bir mod da var —
  `EMERGENT_LLM_KEY` gerektirmez, `HF_TOKEN` gerektirir. Ağır bağımlılıklar
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

İş akışı (`TRANSCRIPTION_BACKEND=api`, varsayılan): `_prepare_chunks()` →
mono/16kHz downsample, ≤20MB parçalara böl → `transcribe_audio()` →
format/boyut doğrula, transcode/chunk, Whisper'a gönder, birleştir →
`_diarize_with_claude()` → Whisper çıktısını claude-sonnet-4-6'ya gönderip
konuşmacı ayrımı yaptır (hata durumunda sessizce None dönüyor).

İş akışı (`TRANSCRIPTION_BACKEND=local`): aynı format/boyut doğrulaması →
`_transcribe_local()` (faster-whisper, segment+timestamp'li) →
`_diarize_local()` (pyannote.audio) → `_align_and_format_diarization()`
(zaman-örtüşmesine göre hizala, "1. kişi/2. kişi" formatına çevir — aynı
sözleşme, diarization başarısız olursa yine sessizce None). Detay: README.md
"Local mode ile çalıştırma".

## Bilinen Kritik Sorunlar

Orijinal 9 maddelik liste (security → docs ajan sırasıyla) — durum güncellendi:

1. ✅ **Çözüldü — CORS güvenlik açığı** (security-agent): `allow_origins='*'`
   kaldırıldı, `CORS_ORIGINS` env değişkeninden liste okunuyor, default
   localhost'a sınırlı.
2. ✅ **Çözüldü — env değişkeni çökmesi** (security-agent): `os.environ.get()`
   + eksik değişkeni adıyla belirten net `RuntimeError`.
3. ✅ **Çözüldü — dosya boyutu limiti tutarsızlığı** (consistency-agent): tek
   kaynak `MAX_UPLOAD_SIZE` (500MB), frontend/backend/PRD senkron.
4. ⚠️ **Kısmen çözüldü — FLAC/OGG:** Artık tutarlı davranıyor (500 yerine net
   400 "desteklenmiyor" hatası — consistency-agent, Seçenek A). **Hâlâ açık:**
   gerçek destek (Seçenek B, server-side transcoding) kod olarak hazır ve
   lokal test edilmiş ama **P2 backlog'ta kapalı duruyor** — infra-agent'ın
   deploy image'ında ffmpeg/ffprobe'un gerçekten kurulu olduğunu doğrulaması
   bekleniyor (bkz. `memory/PRD.md` backlog notu).
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

## Sabit Kurallar (Claude Code her zaman uymalı)

- `pytest.ini` içindeki `addopts`'a **DOKUNMA** — dosyada açık uyarı var:
  "AGENT: do NOT modify addopts" (`-n 2 --dist loadscope`).
- Yeni endpoint/route eklerken mevcut `/api` prefix konvansiyonuna uy.
- MongoDB kaldırıldı (yukarıdaki "Mevcut Mimari" notuna bakın) — yeniden
  eklenecekse karar önce `memory/PRD.md`'de gerekçelendirilsin, sessizce
  eklenmesin.
- Her değişiklik sonrası `backend/tests/backend_test.py` VE
  `backend/tests/test_local_mode.py` çalıştırılıp doğrulansın (`pytest tests/`
  ikisini birden çalıştırır).
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
