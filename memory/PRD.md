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

**2026-07-28 — local mode performans optimizasyonu + model boyutu benchmark'ı**
- `_transcribe_local()` artık ham `WhisperModel.transcribe()` yerine
  faster-whisper'ın `BatchedInferencePipeline`'ını kullanıyor (yeni
  `_get_local_whisper_pipeline()`) — VAD ile bulunan konuşma segmentlerini
  tek tek değil toplu işliyor. 4 çekirdekli bir VPS simülasyonunda
  (`taskset -c 0-3`) ~115s'lik çok-segmentli bir kayıtta ölçülen hızlanma:
  tiny 7.2x (14.94s→2.09s), base 8.5x (32.93s→3.87s), small 7.3x
  (81.02s→11.08s). Yeni `WHISPER_BATCH_SIZE` env değişkeni eklendi
  (varsayılan `8` — 4/8/16 karşılaştırıldı, bu test setinde anlamlı fark
  yoktu, 8 daha uzun/çok-segmentli gerçek kayıtlar için güvenli bir orta yol).
- **Gerçek bir performans bug'ı bulunup düzeltildi:** kod `cpu_threads=
  os.cpu_count()` kullanıyordu — `os.cpu_count()` host makinenin toplam
  çekirdek sayısını döner, cgroup/container/VPS CPU kısıtlamasını GÖRMEZ.
  Bu, bir VPS/container'da gerçek payından fazla thread açılmasına
  (oversubscription) yol açıyordu — kullanıcının gözlemlediği "~117% CPU"
  (4 çekirdekli sistemde ~1 çekirdek civarı) belirtisiyle uyumlu bir kök
  neden. Doğrulama: `taskset -c 0-3` ile 4 çekirdeğe kısıtlı ortamda,
  `cpu_threads=16` (host'un gerçek çekirdek sayısı, `os.cpu_count()`'un
  döneceği değer) `cpu_threads=4`'e (doğru, kısıtlı değer) göre ~%34 daha
  yavaştı ve daha düşük çekirdek kullanım verimliliği gösterdi (2.86 vs 3.65
  "kullanılan çekirdek" — cpu_time/wall_time). Düzeltme: yeni
  `_local_cpu_threads()` fonksiyonu `os.sched_getaffinity(0)` kullanıyor
  (Linux'a özgü, cgroup/`taskset`-farkında; yoksa `os.cpu_count()`'a düşer).
- **Model boyutu (tiny/base/small) karşılaştırması** (batching aktif,
  `cpu_threads=4`, `batch_size=8`): temiz, tek-segmentli gerçek bir kayıtta
  (`jfk.flac`, ~11s) üç model de **kelime düzeyinde aynı** transkripti
  üretti — tek fark noktalama (tiny bir virgülü atladı). Süre farkı belirgin:
  tiny 0.51s, base 0.83s, small 2.21s (small, tiny'den ~4.3x yavaş). Uzun/
  çok-segmentli sentetik bir kayıtta (aynı cümle 9 kez tekrar) üçü de
  kelimeleri doğru transkribe etti ama tekrar arttıkça noktalama tutarlılığı
  düşüyor — `small` en uzun süre (~5 tekrar) noktalamayı koruyor, `base` ~3
  tekrar, `tiny` hiç tutturamadı. **Sonuç:** bu (temiz, tek konuşmacılı)
  test setinde model boyutunun kelime doğruluğuna ölçülebilir bir etkisi
  yok; asıl hedef kullanım senaryosu (gürültülü/düşük kaliteli kayıt) için
  ayrı test önerildi. `WHISPER_MODEL_SIZE` **değiştirilmedi** — env
  değişkeni olarak kalıyor (varsayılan `small`), kod içinde sabitlenmedi.
  Tam metodoloji, ölçüm scripti ve tablolar: `BENCHMARK.md` (yeni dosya).
- Test: `test_transcribe_local_calls_faster_whisper_and_shapes_output`
  artık `BatchedInferencePipeline` çağrısını (model, batch_size, vad_filter)
  doğruluyor; yeni `test_local_cpu_threads_uses_sched_affinity_not_cpu_count`
  regresyon testi eklendi (`os.sched_getaffinity`/`os.cpu_count()` mock'lanıp
  doğru değerin seçildiği doğrulanıyor). Tam paket: 21 test geçti, 4 skip,
  0 hata; canlı sunucuya karşı gerçek bir `/api/transcribe` isteğiyle de
  (local mode, `WHISPER_MODEL_SIZE=tiny`) uçtan uca doğrulandı.

**2026-07-28 — desteklenen dosya formatları genişletildi + gerçek içerik doğrulaması**
- `ALLOWED_EXTS` genişletildi: **`.ogg` yeniden eklendi** — daha önce
  consistency-agent tarafından flac ile birlikte kapatılmıştı (P2 backlog,
  bkz. yukarıdaki ilgili girdi), ama bu değişiklik onu bloke eden iki şeyi de
  kapattı: infra-agent'ın Docker build'inde ffmpeg'in kurulu olduğunu zaten
  doğrulamış olması VE aşağıdaki yeni `_verify_media_stream()`'in gerçek
  içerik doğrulaması sağlaması. **`.flac` bilinçli olarak hâlâ dışarıda** —
  bu karar bu değişiklikle yeniden gözden geçirilmedi. Yeni bir
  **`DVR_EXTS = {"dav"}`** seti eklendi: Dahua ve benzeri DVR/güvenlik
  kamerası kayıtları (genelde H.264 video + G.711/G.726 ses) — standart bir
  konteyner olmadığı için diğer setlerden farklı olarak **best-effort,
  garanti değil** olarak işaretlendi.
- Yeni **`_verify_media_stream(raw_bytes, ext)`** fonksiyonu: her
  `/api/transcribe` isteğinde (TRANSCRIPTION_BACKEND'den bağımsız — hem api
  hem local mode), dosya uzantısına güvenmek yerine gerçekten decode
  edilebilir bir ses akışı içerip içermediğini kontrol ediyor. `ffprobe` CLI
  binary'sine subprocess ile gitmek yerine **PyAV (`av`)** kullanıyor — aynı
  altta yatan libav decode makinesi (ffprobe'un da üzerine kurulu olduğu),
  ama sistemde ayrıca bir `ffmpeg`/`ffprobe` binary'si PATH'te olmasını
  gerektirmiyor (`_decode_waveform_for_pyannote`'ın zaten kullandığı aynı
  yaklaşım/gerekçe). `av` faster-whisper'ın transitive bağımlılığı olduğu
  için opsiyonel: kurulu değilse (teoride API-only bir deploy'da olabilir)
  sessizce eski uzantı-bazlı davranışa düşüyor, "api" modunun temel
  yolunu hard-fail etmiyor. İçerik doğrulaması başarısız olursa: `.dav` için
  ayrı, actionable bir 400 ("Bu DVR kaydı işlenemedi... VLC ile dönüştürüp
  tekrar deneyin"), diğerleri için genel bir "ses akışı bulunamadı" 400'ü.
- Frontend (`Transcriber.jsx`): `AUDIO_EXTRA`'ya `ogg`, yeni `DVR_EXT = ["dav"]`
  eklendi (`VIDEO_SET`'e de dahil edildi — dosya seçilince "Video · Ses
  ayıklanacak" etiketi `.dav` için de görünsün diye), kullanıcıya gösterilen
  format listeleri güncellendi.
- Test: yeni `backend/tests/test_media_validation.py` — `_verify_media_stream`'i
  doğrudan (canlı sunucu olmadan) test ediyor. Gerçek bir `.dav` örneği
  bulunamadı/pratik değildi (ne erişilebilir bir örnek kayıt var, ne de PyAV
  bir DVR vendor'ının kullandığı codec'i encode edebiliyor) — o senaryo
  kasıtlı olarak bozuk/decode-edilemez byte'larla test edildi. Ama **gerçek,
  mock'suz bir pozitif senaryo da var**: PyAV'ın kendi `vorbis` encoder'ı ile
  (sistemde ffmpeg olmadan) gerçek, geçerli, minimal bir Ogg/Vorbis dosyası
  sentezlenip `_verify_media_stream`'in bunu gerçekten kabul ettiği
  doğrulandı — sadece "reddediyor" değil "gerçek içeriği kabul ediyor" da
  test edildi. `backend_test.py`'deki eski `test_rejects_ogg_with_clear_400`
  `test_accepts_ogg_extension_but_rejects_undecodable_content` olarak
  yeniden yazıldı (artık uzantı kabul ediliyor, sahte byte'lar içerik
  kontrolünde reddediliyor) + yeni `test_rejects_undecodable_dav_with_
  actionable_message` eklendi. `test_local_mode.py`'deki bir test
  (`test_transcribe_endpoint_never_calls_diarize_local`, sahte "fake wav
  bytes" kullanıyordu) yeni content-validation'ı da mock'layacak şekilde
  güncellendi. Tam paket: 28 test geçti, 4 skip, 0 hata.
- Not: `.ogg`/`.dav` gibi transcode gerektiren formatların **gerçek uçtan uca**
  (tam transkripsiyon) doğrulaması bu geliştirme ortamında yapılamadı —
  burada sistemde `ffmpeg` binary'si kurulu değil (pydub'ın `AudioSegment.
  from_file` için hâlâ gerektirdiği, `_verify_media_stream`'den bağımsız bir
  ihtiyaç). Docker image'ında ffmpeg zaten kurulu (infra-agent doğrulaması) —
  gerçek bir `.dav`/`.ogg` dosyasıyla tam pipeline'ın orada test edilmesi
  öneriliyor.

**2026-07-28 — large-v3-turbo benchmark'a eklendi**
- faster-whisper 1.2.1'in `available_models()` listesi `large-v3-turbo`'yu
  zaten içeriyor; `WHISPER_MODEL_SIZE` serbest metin olduğu (bir whitelist'e
  karşı doğrulanmadığı) için **kod değişikliği gerekmedi** — `.env`'de
  `WHISPER_MODEL_SIZE=large-v3-turbo` yazmak yeterli. Gerçek sunucu üzerinden
  (`TRANSCRIPTION_BACKEND=local`) canlı bir `/api/transcribe` isteğiyle
  doğrulandı (ilk kullanımda ~1.6 GB model indiriyor).
- Benchmark script'i (`BENCHMARK.md`'deki, artık `BENCH_LANGUAGE` env
  değişkenini de destekliyor) `large-v3-turbo`'yu içerecek şekilde
  genişletildi. Hız: `small`'a göre tutarlı şekilde ~3x daha yavaş (3
  farklı kayıtta ölçüldü: 2.6x-3.6x arası).
- Doğruluk — İngilizce, temiz kayıt (`jfk.flac`): önceki bulguyla aynı,
  kelime düzeyinde fark yok.
- Doğruluk — Türkçe (yeni test verisi): gTTS ile (bu ölçüm için geçici
  olarak kurulup hemen sonra kaldırıldı, projeye bağımlılık olarak
  eklenmedi) gerçek bir ~20s Türkçe kayıt sentezlendi (Türkçe'ye özgü
  karakterler/kelimeler içeren 3 cümle). Hem `small` hem `large-v3-turbo`
  kelime/anlam hatası yapmadı — tek somut fark `large-v3-turbo`'nun sayıları
  rakama normalize etmesi ("saat üçte"→"saat 3'te", "yüzde on ikiye"→"%12'ye"),
  `small` ise konuşmadaki gibi yazıyla bırakıyor. gTTS stüdyo-kalitesinde
  olduğu için gürültülü/düşük kaliteli gerçek Türkçe kayıtla doğrulama hâlâ
  açık (bkz. önceki changelog girdisinin "Değerlendirme" notu, aynı kısıt
  geçerli).
- Doğruluk — daha zor/belirsiz bir İngilizce klip (`jfk.wav`, "she had your
  dark suit in greasy wash water all year"): burada **model boyutu gerçekten
  fark yarattı ve monoton değildi** — `tiny` 1 hata, `small` 3 hata (`tiny`'den
  DAHA KÖTÜ), `large-v3-turbo` 1 hata (en az). Önceki benchmark turunun
  "temiz sesle model boyutu fark etmiyor" sonucunun sadece kolay/net bir
  kayıtla sınırlı olduğunu gösteren somut bir karşı-örnek — tek bir 2.9s
  klip, genellemek için yeterli değil ama not edilmeye değer.
- `WHISPER_MODEL_SIZE` **değiştirilmedi** — env değişkeni olarak kalıyor,
  varsayılan hâlâ `small`. Tam metodoloji, tablolar, kaynak metin ve
  script güncellemesi: `BENCHMARK.md` "Bulgu 4".

**2026-07-28 — per-istek quality_mode (hız/doğruluk seçimi)**
- Önceki benchmark turunun bulgusu üzerine (large-v3-turbo bazı zor/gürültülü
  kayıtlarda daha doğru ama ~3x yavaş), kullanıcının `.env`'de sabit bir
  seçim yapmak yerine **her istekte** hız/doğruluk arasında seçim
  yapabilmesi sağlandı: `/api/transcribe`'a yeni bir opsiyonel form alanı,
  `quality_mode` (`"standard"` varsayılan, veya `"precise"`). Local mode'da
  `"standard"` → `WHISPER_MODEL_SIZE` (env), `"precise"` → her zaman
  `large-v3-turbo` (env'den bağımsız, sabit — `PRECISE_MODEL_SIZE`). Geçersiz
  bir `quality_mode` değeri net bir 400 ile reddediliyor. api mode bu alanı
  yok sayıyor (sadece local mode'u etkiliyor, görev tanımı gereği).
- Model/pipeline cache'i `quality_mode` anahtarlı bir dict'e taşındı
  (`_local_whisper_models`, `_local_whisper_pipelines` — önceden tek bir
  modül-seviyesi global değişkendi). `_get_local_whisper_model(quality_mode)`
  sadece o `quality_mode` fiilen istendiğinde model yükler ve cache'ler;
  `_model_size_for_quality()` `quality_mode`'u gerçek model boyutu string'ine
  çeviriyor. Bu, iki modelin GEREKSİZ yere aynı anda belleğe yüklenmesini
  önlüyor (istenmeyen mod hiç yüklenmez) ama aynı moddaki art arda gelen
  istekler için cache/yeniden-kullanım sağlıyor (görev gereksinimi tam
  olarak buydu).
- Frontend (`Transcriber.jsx`): `qualityMode` state'i (varsayılan
  `"standard"`), form'a `quality_mode` alanı eklendi, dosya seçili panelinde
  iki buton — "Hızlı (standart)" (varsayılan seçili) ve "Hassas (yavaş,
  gürültülü/zor kayıtlar için)" — ve BENCHMARK.md Bulgu 4'ü özetleyen kısa
  bir açıklama metni eklendi.
- Test: `test_local_mode.py`'ye yeni `TestQualityMode` sınıfı — mock'lu
  (gerçek model indirmeden): `_model_size_for_quality` çözümlemesi
  (`"standard"`→env, `"precise"`→her zaman `large-v3-turbo`, env'i override
  ettiği dahil), cache'in `quality_mode` başına ayrı tutulduğu, bir modun
  diğerini asla tetiklemediği (RAM gereksinimi), aynı moddaki tekrar
  isteklerin cache'i kullandığı (yeniden yükleme yok), `TestClient` ile
  gerçek endpoint üzerinden `quality_mode`'un `_transcribe_local`'a doğru
  forward edildiği (hem "precise" hem varsayılan "standard" için) ve
  geçersiz bir `quality_mode`'un 400 ile reddedildiği. Tam paket (kod
  değişikliği olduğu için backend_test.py + test_local_mode.py +
  test_media_validation.py hepsi çalıştırıldı).
- Detay ve tam gerekçe: `BENCHMARK.md` "Bulgu 5".

**2026-07-28 — duraklama-tabanlı satır kırma (okunabilirlik, diarization DEĞİL)**
- `text` alanı artık düz tek paragraf değil: iki konuşma birimi arasındaki
  boşluk `PAUSE_THRESHOLD_SECONDS`'ı (1.3s, kod içinde sabit — env değil,
  bilinçli olarak) aştığında `\n` ile satırlara bölünüyor. Yeni
  `_format_transcript_with_pauses()` fonksiyonu hem `_transcribe_local`
  (local mode) hem `transcribe_audio`'nun api-mode dalında kullanılıyor.
  **Konuşmacı etiketi ("1. kişi" vb.) EKLENMEDİ** — bu kasıtlı olarak sadece
  okunabilirlik amaçlı satır kırma, `diarized_text` alanına hiç dokunulmadı
  (görev tanımının açık kısıtı).
- **Gerçek, testte bulunan bir tasarım sorunu ve düzeltmesi:** İlk tasarım
  Whisper'ın kendi ürettiği segment (cümle/ifade seviyesi) sınırlarını
  kullanıyordu — ama gerçek bir sentetik test klibiyle (JFK konuşması + 3
  saniyelik sessizlik + tekrar) doğrudan test edildiğinde,
  `BatchedInferencePipeline`'ın (local mode'un performans için kullandığı,
  bkz. BENCHMARK.md Bulgu 2) VAD ile ayırdığı iki konuşma bloğunu TEK bir
  kaba `Segment`'te birleştirdiği görüldü — 3 saniyelik boşluk segment
  sınırlarında hiç görünmedi, tüm 25 saniyelik klip tek segment olarak
  döndü. Çözüm: `word_timestamps=True` ile **kelime seviyesi** zaman
  damgaları kullanıldı (segment değil) — aynı test klibinde kelimeler
  arasındaki 3.36s'lik boşluk doğru tespit edildi (`_transcribe_local`
  artık hem eski segment-seviyesi `whisper_segments`'i — değişmeden,
  diarization alignment için — hem ayrı bir kelime listesini döndürüyor,
  ikincisi sadece satır kırma için kullanılıyor).
- API mode'da da tutarlılık için aynı kelime-seviyesi yaklaşım kullanıldı:
  `response_format=verbose_json` + `timestamp_granularities=["word"]`
  (önceden `response_format=json`, hiç zaman damgası yoktu). OpenAI'nin
  gerçek API'sinde local mode'daki aynı "segment birleştirme" sorununun
  olup olmadığı bu dev ortamında test edilemedi (`EMERGENT_LLM_KEY` yok) —
  varsayımda bulunmak yerine iki modda da aynı, gerçekten test edilmiş
  granülarite (kelime) kullanılması tercih edildi. Sağlam bir soft-fail
  zinciri var: kelime zaman damgaları yoksa segment'lere, o da yoksa düz
  `response.text`'e düşer.
- `PAUSE_THRESHOLD_SECONDS = 1.3` saniye seçildi (normal cümle-içi nefes
  duraklamaları genelde <1s, kasıtlı cümleler/konu arası duraklamalar
  genelde 1.5s+ — bu projenin hedef içeriği olan röportaj/toplantı
  kayıtlarında). Ölçülmüş bir değer değil, gerekçeli bir varsayılan —
  gerekirse `backend/server.py`'de değiştirilebilir (env değişkeni değil,
  görev tanımı gereği).
- Gerçek sunucu üzerinden hem sentetik duraklamalı (3s sessizlik → satır
  kırıldı, doğrulandı) hem gerçek doğal konuşmayla (jfk.wav, kısa/duraksız
  → tek satır kaldı, gereksiz bölünme yok) doğrulandı.
- Frontend (`Transcriber.jsx`): Kod değişikliği gerekmedi — metin zaten
  `white-space: pre-wrap` CSS class'ıyla render ediliyordu (önceden
  diarized_text'in çok satırlı "1. kişi:\n2. kişi:" formatı için eklenmişti),
  bu da `\n` karakterlerini otomatik satır sonu olarak gösteriyor. Doğrulandı.
- Test: `test_local_mode.py`'ye `TestFormatTranscriptWithPauses` (saf mantık,
  boşluk eşiği sınır durumu dahil, 7 test), `TestNormalizeOpenAISegments`
  (api-mode segment/kelime normalizasyonu, 4 test) ve `_transcribe_local`'ın
  gerçekten pause-formatting'e sarıldığını doğrulayan bir entegrasyon testi
  eklendi. Tam paket: 49 test geçti, 4 skip, 0 hata.
