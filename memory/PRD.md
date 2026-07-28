# SesDeşifre — PRD

## Original Problem Statement
> bir ses dosyasını yazıya donusturen web sitesi yap. ses dosasyında sesler kalitesiz olabilir dusuk frekans olabilir

Türkçe arayüzlü, ses dosyasını metne çeviren tek sayfa bir web uygulaması. Düşük kaliteli / düşük frekanslı sesler destekleniyor.

## User Personas
- **Türkçe içerik üreticisi** — röportaj, ses notu veya toplantı kayıtlarını metne çevirmek isteyen kişi
- **Araştırmacı / gazeteci** — gürültülü saha kayıtlarını transkribe etmek isteyen kullanıcı
- **Genel kullanıcı** — hızlıca ses dosyası yükleyip metnini almak isteyen kişi (giriş yapmadan)

## Core Requirements (static)
- Türkçe arayüz
- Ses dosyası yükleme (drag & drop + tıkla)
- Desteklenen formatlar: mp3, wav, m4a, webm, mp4, mpeg, mpga (Whisper resmi listesi) +
  server-side transcode edilen ek formatlar (backend/server.py EXTRA_AUDIO_EXTS/VIDEO_EXTS).
  flac/ogg şu an İSTİSNA — bkz. Backlog.
- Max 500 MB (backend `MAX_UPLOAD_SIZE`, frontend `MAX_SIZE_MB` ile senkron). Not: Whisper'ın
  gerçek per-request teknik limiti 25 MB'dir (`WHISPER_LIMIT`) — bu, kullanıcıya gösterilen bir
  sınır değil; 500 MB'a kadar dosyalar sunucu tarafında ≤20 MB parçalara bölünüp (`_prepare_chunks`)
  Whisper'a ayrı ayrı gönderilir. (2026-07-23, consistency-agent: üç farklı yerdeki üç farklı
  değer — frontend 40MB/backend 500MB/PRD 25MB — tek kaynağa indirildi; 25MB'a düşürülmedi çünkü
  bu, zaten çalışan parçalama özelliğini devre dışı bırakırdı.)
- Düşük kaliteli / düşük frekans seslere uygun (Whisper + gürültü işleme prompt)
- Metin sonucu görüntüleme + Panoya kopyala + TXT indir
- Hesap yok, geçmiş yok

## Architecture
- **Frontend**: React (CRA) + Tailwind + shadcn/ui + framer-motion + sonner
- **Backend**: FastAPI (`/api/transcribe`), `emergentintegrations.llm.openai.OpenAISpeechToText` (whisper-1)
- **DB**: Yok. MongoDB bağlantısı 2026-07-23'te cleanup-agent tarafından kaldırıldı — sebep:
  hiç CRUD/model/koleksiyon kullanılmıyordu, tek potansiyel kullanım alanı "kayıt geçmişi"
  P2 backlog'ta (yakın vadeli değil, hesap sistemi de gerektiriyor). `motor`/`pymongo`/`dnspython`
  `requirements.txt`'ten çıkarıldı. İleride kayıt geçmişi özelliği önceliklenirse MongoDB (veya
  başka bir DB) o zaman, o özelliğin gereksinimlerine göre yeniden değerlendirilip eklenmeli.
- **Auth**: API-key header (`X-API-Key`) + rate limiting (`slowapi`, `POST /api/transcribe`
  için IP başına 5/dakika). 2026-07-23'te eklendi — bkz. `SECURITY_NOTES.md`. JWT/çok-kullanıcılı
  sistem YOK (bilinçli karar; proje tek-kullanıcılı/dahili kullanım için tasarlanıyor).
- **Transkripsiyon backend'i**: `TRANSCRIPTION_BACKEND` env değişkeni ile seçilir.
  `api` (varsayılan, değişmedi) — Whisper API + Claude. `local` (2026-07-28 eklendi) —
  faster-whisper + pyannote.audio, tamamen yerel/offline, `EMERGENT_LLM_KEY` gerekmez,
  `HF_TOKEN` gerekir. Bkz. README.md "Local mode ile çalıştırma".
- **Env**: `EMERGENT_LLM_KEY` (universal key, api modu), `API_KEY` (transcribe endpoint
  auth), `TRANSCRIPTION_BACKEND`/`WHISPER_MODEL_SIZE`/`HF_TOKEN` (local mod, opsiyonel)

## Implemented (2026-02)
- ✅ POST `/api/transcribe` — çoklu-part yükleme, dosya uzantı + boyut kontrolü, Whisper çağrısı, Türkçe hata mesajları
- ✅ GET `/api/health` sağlık uçnoktası
- ✅ Frontend: Swiss High-Contrast tasarımlı tek sayfa uygulama (`SesDeşifre`)
- ✅ Sürükle-bırak + tıkla ile yükleme, ilerleme çubuğu, sonuç paneli
- ✅ Panoya Kopyala, TXT İndir, Yeni Dosya, Vazgeç butonları
- ✅ Sonner ile Türkçe toast bildirimleri
- ✅ Test agent tarafından full-stack doğrulama (8/8 backend, frontend akışları OK)

## Deferred / Backlog
- **P1**: Zaman damgalı transkripsiyon (`verbose_json` + `segments`) ve SRT/VTT indirme
- ✅ **P1 (tamamlandı, kod zaten mevcuttu, PRD güncel değildi)**: 25 MB üstü dosyalar için
  server-side ffmpeg ile parçalama — `backend/server.py` `_prepare_chunks()` bunu zaten yapıyor
  (mono/16kHz/MP3 64kbps, ≤20MB parçalar). 2026-07-23'te consistency-agent bunu keşfetti ve
  frontend/backend/PRD arasındaki limit tutarsızlığını buna göre düzeltti.
- **P2 — FLAC/OGG server-side transcoding (Option B), şu an bilerek KAPALI**: Kod yolu
  (`_prepare_chunks` → pydub/ffmpeg) FLAC için 2026-07-23'te lokal olarak çalışan bir
  ffmpeg+ffprobe ile test edildi ve BAŞARILI oldu (jfk.flac → mp3'e doğru şekilde transcode
  edildi). Yani üretimde görülen "500 + ham provider hatası" muhtemelen deploy ortamında
  ffmpeg/ffprobe'un PATH'te bulunmamasından kaynaklanıyor — kod mantığı değil, bir altyapı
  eksikliği. consistency-agent, kanıtlanamayan bir üretim varsayımına güvenmek yerine güvenli
  varsayılanı (Seçenek A) uyguladı: flac/ogg `ALLOWED_EXTS`'ten çıkarıldı, artık net bir 400
  "Desteklenmeyen format" hatası dönüyor. **infra-agent görevi**: deploy image'ında
  `ffmpeg`/`ffprobe` binary'lerinin gerçekten kurulu olduğunu doğrula; doğrulanırsa flac/ogg
  `EXTRA_AUDIO_EXTS`'e geri eklenip Seçenek B resmen etkinleştirilebilir.
- **P2**: Otomatik dil algılama seçeneği (şu an sabit `tr`)
- **P2**: Kayıt geçmişi (opsiyonel; hesap gerektirir)
- **P2**: Tarayıcıda mikrofon kaydı → doğrudan transkripsiyon

## Next Tasks
1. Kullanıcı geri bildirimi topla; en çok istenen özelliği belirle
2. Zaman damgaları + SRT indirme (P1)
3. infra-agent: ffmpeg/ffprobe deploy image doğrulaması → FLAC/OGG'u yeniden etkinleştir (P2)

## Profesyonelleştirme Geçmişi

Emergent AI-agent platformundan çıkan "temizlenmemiş prototip" MVP'nin
orchestrator + alt ajan modeliyle production-ready hale getirilme günlüğü.
Sıralama: security → cleanup → consistency → test → infra → docs (CLAUDE.md
"Çalışma Yöntemi"). Detaylar için ilgili commit'ler ve `SECURITY_NOTES.md`.

**2026-07-23 — security-agent**
- CORS: `allow_origins='*'` + `allow_credentials=True` (geçersiz/riskli
  kombinasyon) kaldırıldı; `CORS_ORIGINS` env değişkeninden virgülle ayrılmış
  liste okunuyor, tanımsızsa güvenli localhost default'u kullanılıyor.
- `MONGO_URL`/`DB_NAME` doğrudan `os.environ[...]` indekslemesi (sessiz
  `KeyError`) → `.get()` + anlaşılır `RuntimeError` mesajı.
- `_diarize_with_claude`'daki hata yutma zaten `logger.exception` ile
  logluyormuş (ek değişiklik gerekmedi — CLAUDE.md'deki eski tespit güncel
  değilmiş).
- `SECURITY_NOTES.md` oluşturuldu: auth/rate-limit DEĞERLENDİRMESİ (henüz
  implementasyon değil).

**2026-07-23 — consistency-agent**
- Dosya boyutu limiti: frontend 40MB / backend 500MB / PRD 25MB
  tutarsızlığı → tek kaynak `MAX_UPLOAD_SIZE` (500MB); 25MB'a
  düşürülmedi çünkü bu, zaten çalışan `_prepare_chunks` parçalama
  özelliğini devre dışı bırakırdı (bkz. yukarıdaki backlog notu).
- FLAC/OGG: Seçenek A uygulandı (`ALLOWED_EXTS`'ten çıkarıldı, net 400
  hatası); Seçenek B (server-side transcoding) kod olarak hazır ve test
  edilmiş durumda ama altyapı doğrulanana kadar kapalı (bkz. backlog).

**2026-07-23 — test-agent (backend ortamı + frontend test altyapısı)**
- `backend/.venv` + `pytest` ortamı kuruldu; gerçek Whisper/Claude API
  çağrısı gerektiren testler `@pytest.mark.skip` (`REQUIRES_REAL_API`) ile
  işaretlendi (silinmedi).
- Frontend'de daha önce SIFIR test vardı → Jest + React Testing Library
  kuruldu (`@testing-library/react` v16, React 19 uyumlu),
  `src/pages/Transcriber.test.jsx` + `src/setupTests.js` eklendi.
- Python 3.13'te pydub'ı kıran `audioop` stdlib kaldırımı keşfedildi →
  `audioop-lts` bağımlılığı eklendi (`python_version >= "3.13"` koşullu).

**2026-07-23 — cleanup-agent**
- Kullanılmayan 8 bağımlılık (`stripe`, `python-jose`, `PyJWT`, `passlib`,
  `bcrypt`, `google-generativeai`, `google-genai`, `boto3`) `grep` ile
  doğrulanıp `requirements.txt`'ten kaldırıldı (auth kararı JWT
  gerektirmediği için hiçbiri "ayrılmış" tutulmadı).
- **MongoDB tamamen kaldırıldı**: hiç CRUD/model kullanılmıyordu, tek
  potansiyel kullanım alanı (kayıt geçmişi) P2 backlog'ta, yakın vadeli
  değil. `motor`/`pymongo`/`dnspython` de `requirements.txt`'ten çıkarıldı.

**2026-07-23 — auth/rate-limit implementasyonu (orchestrator kararı)**
- Karar: basit API-key header + rate limiting; JWT/çok-kullanıcılı sistem
  YOK (bkz. yukarıdaki "Auth" notu).
- Backend: `X-API-Key` header kontrolü (`require_api_key`, 401), `slowapi`
  ile `POST /api/transcribe` için IP başına 5/dakika rate limit (429).
  `SECURITY_NOTES.md` "UYGULANDI" olarak güncellendi.
- Frontend: `REACT_APP_API_KEY` env değişkeni axios isteğine `X-API-Key`
  olarak ekleniyor; README'ye bu değerin tarayıcı bundle'ında görünür
  olduğu, gerçek sır olmadığı uyarısı eklendi.
- Test: auth/rate-limit senaryoları için yeni testler + mevcut testlere
  `AUTH_HEADERS` eklendi (kırılmadılar).

**2026-07-24 — infra-agent**
- `backend/Dockerfile` (Python 3.11-slim + ffmpeg + `--workers 1`, slowapi
  in-memory storage yüzünden — yorumla belgelendi), `frontend/Dockerfile`
  (multi-stage, Nginx serve, `REACT_APP_*` build-arg olarak geçiyor),
  `frontend/nginx.conf` (`/api` reverse proxy, 500MB upload limiti, uzun
  timeout), kök `docker-compose.yml` (MongoDB servisi YOK — kaldırıldığı
  için eklenmedi) ve `.github/workflows/ci.yml` (opsiyonel CI) eklendi.
- `docker compose up` ile ayakta kalma, health-check ve auth 401/200
  senaryoları hem container içinden hem host üzerinden (nginx reverse-proxy
  zinciri dahil) doğrulandı. **Not**: build sırasında sandbox'a özgü bir ağ
  kısıtlaması (`docker compose build`'ın DNS çözemediği) `docker build
  --network host` ile aşıldı — normal bir ortamda beklenmez ama gerçek bir
  CI/deploy ortamında ayrıca doğrulanmadı.

**2026-07-24 — docs-agent**
- `README.md` placeholder'dan gerçek içeriğe geçirildi (mimari özeti,
  kurulum: lokal backend/frontend + Docker, test çalıştırma, API tablosu).
- `.env.example` dosyaları (`backend/`, `frontend/`, kök) gözden geçirildi;
  frontend'e eksik olan opsiyonel `ENABLE_HEALTH_CHECK` eklendi.
- Bu "Profesyonelleştirme Geçmişi" bölümü ve `CLAUDE.md`'nin "Bilinen
  Kritik Sorunlar" listesi güncel duruma göre revize edildi.

**2026-07-28 — local mode (dış API bağımlılığı olmayan transkripsiyon/diarization)**
- `TRANSCRIPTION_BACKEND` env değişkeni eklendi (`api` varsayılan, davranış
  değişmedi; `local` — faster-whisper + pyannote.audio, `EMERGENT_LLM_KEY`
  gerekmez). Ağır bağımlılıklar (`torch` dahil, pyannote.audio üzerinden)
  `server.py`'de lazy-import edilir — "api" modu bu paketler kurulu olmasa
  bile çalışmaya devam eder.
- `_transcribe_local`/`_diarize_local`/`_align_and_format_diarization`
  eklendi; pyannote'un (konuşmacı, başlangıç, bitiş) segmentleri Whisper'ın
  zaman damgalı segmentleriyle en-büyük-örtüşme mantığıyla hizalanıp mevcut
  "1. kişi / 2. kişi" metin formatına dönüştürülüyor — frontend hiç
  değişmeden çalışıyor.
- **Gerçek bir HF token'la (kullanıcı sağladı) manuel olarak uçtan uca
  doğrulandı — konuşmacı ayrımı da dahil, gerçekten çalışan `diarized_text`
  ile.** Bu süreçte dört gerçek sorun bulunup düzeltildi:
  1. `Pipeline.from_pretrained()`'ın kwarg'ı pyannote.audio 4.x'te
     `use_auth_token`'dan `token`'a değişmiş (kod düzeltildi).
  2. `pyannote/speaker-diarization-3.1`, 4.x'te ayrı ve gated bir modele
     (`pyannote/speaker-diarization-community-1`) bağımlı — ilk denemede
     kullanıcının token'ı sadece 3.1'e erişim onaylıydı, `403 GatedRepoError`
     aldık (kullanıcı sonradan community-1'i de onayladı). README.md'ye bu
     adım netçe eklendi.
  3. pyannote 4.x dosya okuma için `torchcodec` kullanıyor, o da sistemde
     kurulu ffmpeg paylaşımlı kütüphaneleri (`libavutil.so` vb.) gerektiriyor
     — bu geliştirme makinesinde yok (Docker image'ında VAR, `apt-get install
     ffmpeg`, bkz. `backend/Dockerfile`). Çözüm: `_decode_waveform_for_pyannote`
     eklendi — ses, dosya yolu yerine `av` (faster-whisper'ın zaten bağımlılığı,
     statik bağlı, sistem ffmpeg'i gerektirmiyor) ile kendimiz decode edilip
     pyannote'a doğrudan `{'waveform': tensor, 'sample_rate': int}` olarak
     veriliyor — pyannote'un kendi hata mesajının önerdiği tam olarak bu.
  4. pyannote 4.x, pipeline çağrısından artık düz bir `Annotation` değil
     `DiarizeOutput` dataclass'ı döndürüyor (`.speaker_diarization` alanı
     asıl `Annotation`) — `_diarize_local` buna göre güncellendi.
  Bu dört düzeltmeden sonra, JFK kaydı + gerçekten farklı bir ses (gTTS ile
  sentezlenmiş, sadece bu manuel testi için — projeye eklenmedi) birleştirilen
  bir dosyada `/api/transcribe` **doğru** `"1. kişi: ... / 2. kişi: ... /
  1. kişi: ..."` çıktısını üretti — aynı konuşmacının tekrar göründüğünde
  yeni bir numara almadığı (ilk-görünüş sırasına göre numaralandırma) da
  doğrulandı. Diarization pipeline'ı gerçekten başarısız olduğunda (örn.
  erişim sorunu) soft-fail sözleşmesi (`diarized_text: null`, hata loglanır,
  istek 500 ile çökmez) de ayrıca doğrulanmıştı.
- Test: `backend/tests/test_local_mode.py` (yeni dosya) — config/fail-fast
  senaryoları, `_align_and_format_diarization` (gerçek, mock'suz — saf
  mantık), `_transcribe_local`/`_diarize_local` (faster-whisper/
  pyannote.audio `sys.modules` enjeksiyonuyla mock'landı, bu paketler kurulu
  olmasa bile çalışır). Gerçek model indirmesi gerektiren senaryolar
  `@pytest.mark.skip` ile işaretlendi (yukarıdaki manuel doğrulamaya
  referans veriyor). Mevcut `backend_test.py` (api modu) değişmeden geçmeye
  devam ediyor — 19 test geçti, 4 skip, 0 hata.

**2026-07-28 — local mode'da diarization devre dışı bırakıldı**
- Diarization (yukarıdaki round'da uçtan uca doğrulanmış, çalışır durumdaki
  `_diarize_local`/`_align_and_format_diarization`) local mode'da **devre dışı
  bırakıldı**: hedef deploy ortamı GPU'suz bir VPS, ve pyannote.audio'nun
  Whisper'ın üzerine eklediği CPU süresi kabul edilemez bulundu. Local mode'un
  önceliği artık sadece transkripsiyon hız/doğruluğu — konuşmacı ayrımı olmadan.
- Kod **silinmedi**: `backend/server.py`'nin `transcribe_audio()` fonksiyonunda
  `_diarize_local`/`_align_and_format_diarization` çağrısı yorum satırına
  alındı, net bir açıklayıcı yorumla neden ve nasıl geri açılacağı belirtildi.
  `diarized_text` local modda artık her zaman `null`. `HF_TOKEN` fail-fast
  kontrolü de kasıtlı olarak kaldırılmadı (ileride tekrar açılabilsin diye).
- `_transcribe_local()`'a doğruluğu koruyan/artıran iki faster-whisper ayarı
  eklendi: `vad_filter=True` (sessizlik atlama — hız + doğruluk, yanlış
  transkript üretmiyor) ve `WhisperModel(cpu_threads=os.cpu_count())` (mevcut
  donanımı tam kullan). `beam_size`'a bilinçli olarak dokunulmadı — bu bir
  doğruluk/hız trade-off'u ve kullanıcı doğruluğu önceliklendirdi.
- Frontend (`Transcriber.jsx`) değişmedi: `hasDiarization = Boolean(result
  ?.diarized_text)` zaten `null` durumunu handle ediyor, diarization UI'ı
  otomatik gizleniyor — teyit edildi, ek değişiklik gerekmedi.
- Test: `test_local_mode.py`'ye yeni bir sınıf eklendi
  (`TestLocalModeDiarizationDisabled`) — `TestClient` ile `/api/transcribe`'ı
  local modda çağırıp `_diarize_local`/`_align_and_format_diarization`'ın hiç
  çağrılmadığını ve `diarized_text`'in `null` döndüğünü doğruluyor. Mevcut
  `_transcribe_local` mock testi yeni `vad_filter`/`cpu_threads` argümanlarını
  doğrulayacak şekilde güncellendi. Ayrıca bağımsız bir flake düzeltildi:
  `test_local_mode_imports_without_error`, `backend/.env`'deki
  `WHISPER_MODEL_SIZE=tiny` (önceki manuel doğrulama turundan kalma) aynı
  xdist worker'da `backend_test.py`'nin `load_dotenv` çağrısından sızıp
  testi non-deterministik kırıyordu — artık `WHISPER_MODEL_SIZE` testte
  açıkça `delenv` ediliyor. Tam paket: 20 test geçti, 4 skip, 0 hata.
