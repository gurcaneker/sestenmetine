# SesDeşifre

Ses (ve video) dosyalarını OpenAI Whisper ile Türkçe/İngilizce metne döken,
opsiyonel olarak Anthropic Claude ile konuşmacı ayrımı (diarization) yapan
tek sayfalık bir transkripsiyon uygulaması. Düşük kaliteli/düşük frekanslı
kayıtlar (röportaj, saha kaydı, toplantı notu) için optimize edilmiş; hesap
sistemi yok, dosyanızı yükleyip metni alırsınız.

Kimler için: içerik üreticileri, araştırmacı/gazeteciler, hızlıca bir ses
kaydını metne çevirmek isteyen herkes. Detaylı persona/gereksinim listesi
için bkz. [`memory/PRD.md`](memory/PRD.md).

## Mimari Özeti

- **Backend**: FastAPI (tek dosya, [`backend/server.py`](backend/server.py)) —
  `POST /api/transcribe` dosya yükleme/format doğrulama/gerekirse ffmpeg ile
  transcode+parçalama yapıp Whisper'a gönderir, ardından isteğe bağlı Claude
  diarization uygular. `TRANSCRIPTION_BACKEND=local` ile dış API'sız,
  tamamen yerel (faster-whisper + pyannote.audio) çalışabilir — bkz. aşağıda
  "Local mode ile çalıştırma".
- **Frontend**: React 19 + CRA/craco, tek bileşen
  ([`frontend/src/pages/Transcriber.jsx`](frontend/src/pages/Transcriber.jsx)),
  shadcn/ui + Tailwind (Swiss/High-Contrast tasarım — bkz.
  [`design_guidelines.json`](design_guidelines.json), burada tekrar edilmiyor).
- **Veritabanı**: Yok. MongoDB tamamen kaldırıldı (bkz. `memory/PRD.md`
  Architecture bölümü) — kullanılmıyordu.
- **Auth**: `X-API-Key` header'ı (backend `API_KEY` env değişkeniyle
  eşleşmeli, yoksa `401`) + `POST /api/transcribe` için IP başına 5/dakika
  rate limiting. Detay: [`SECURITY_NOTES.md`](SECURITY_NOTES.md).
- **Deploy**: Docker + Docker Compose (`backend/Dockerfile`,
  `frontend/Dockerfile` + Nginx, kök `docker-compose.yml`) ve basit bir
  GitHub Actions CI pipeline'ı (`.github/workflows/ci.yml`).
- `.emergent/` — projenin çıktığı Emergent AI-agent platformuna özgü
  yapılandırma dosyaları (cloud build/deploy meta verisi); bu repo artık o
  platforma bağımlı değil, sadece geçmişten kalma referans olarak duruyor.

Tüm bilinen sorunlar/kararlar için: [`CLAUDE.md`](CLAUDE.md) (proje durumu,
kısıtlar) ve [`memory/PRD.md`](memory/PRD.md) (gereksinimler + değişiklik
günlüğü).

## Kurulum

### Backend (lokal, Docker olmadan)

```bash
cd backend
python3 -m venv .venv  # veya: python3 -m virtualenv .venv (ensurepip yoksa)
.venv/bin/pip install -r requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
cp .env.example .env
# .env içini doldurun: API_KEY zorunlu (üretmek için aşağıya bakın),
# EMERGENT_LLM_KEY olmadan /api/transcribe 500 döner ama sunucu açılır.
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
.venv/bin/uvicorn server:app --reload
```
Sunucu `http://127.0.0.1:8000` üzerinde açılır (`/api/health` ile doğrulayın).
ffmpeg sisteminizde kurulu olmalı (pydub buna bağımlı — transcode/parçalama
için, bkz. `backend/Dockerfile` yorumu).

### Frontend (lokal, Docker olmadan)

```bash
cd frontend
cp .env.example .env
# REACT_APP_BACKEND_URL (örn. http://127.0.0.1:8000) + REACT_APP_API_KEY
# (backend/.env'deki API_KEY ile AYNI değer) — aşağıdaki uyarıyı okuyun.
yarn install
yarn start
```
`http://localhost:3000` üzerinde açılır.

**`REACT_APP_API_KEY` hakkında önemli uyarı:** Bu değer, build sırasında
tarayıcı bundle'ının içine gömülür ve derlenmiş JS dosyasında düz metin
olarak görünür — **gizli bir sır değildir**, sadece kaba kullanım/bot engeli
sağlar (rastgele bir botun/scriptin `/api/transcribe`'a doğrudan istek atmasını
zorlaştırır, ama isteyen herkes tarayıcı devtools'tan bu değeri okuyabilir).
**Gerçek erişim kontrolü network seviyesinde yapılmalıdır** (VPN, IP allowlist,
Nginx/reverse-proxy seviyesinde auth, vb.) — bkz. `SECURITY_NOTES.md`.

### Docker ile (backend + frontend + Nginx)

```bash
cp .env.example .env
# API_KEY + EMERGENT_LLM_KEY + REACT_APP_API_KEY (API_KEY ile aynı) doldurun.
# REACT_APP_BACKEND_URL'i boş bırakın — frontend, Nginx'in /api reverse
# proxy'si üzerinden backend'e relatif path ile konuşur (bkz. docker-compose.yml).
docker compose up --build
```
Frontend `http://localhost:3000`, backend doğrudan `http://localhost:8000`
üzerinden erişilebilir. `REACT_APP_*` değişkenleri **build-time** olduğu için
(CRA, JS bundle'ına gömer) değiştirirseniz `docker compose build frontend
--no-cache` ile yeniden derlemeniz gerekir — sadece container'ı yeniden
başlatmak yetmez.

> **Not:** Bu repo'daki Docker imajları network erişimi kısıtlı bir sandbox'ta
> `docker build --network host` ile build edilip `docker compose up` ile
> ayakta olduğu doğrulandı (health-check + auth 401/200 senaryoları dahil).
> Normal bir geliştirme makinesinde/CI runner'da `docker compose up --build`
> sorunsuz çalışması beklenir, ama bu — sandbox'a özgü ağ kısıtlaması yüzünden
> — ayrıca doğrulanmadı.

### Local mode ile çalıştırma (dış API bağımlılığı yok)

Varsayılan davranış (`TRANSCRIPTION_BACKEND=api`) OpenAI Whisper API +
Anthropic Claude kullanır (`EMERGENT_LLM_KEY` gerekir). Alternatif olarak
`TRANSCRIPTION_BACKEND=local` ile transkripsiyon (**faster-whisper**)
tamamen yerelde, ilk model indirmesinden sonra **offline** çalışır —
`EMERGENT_LLM_KEY` gerekmez.

> ⚠️ **Diarization (konuşmacı ayrımı) local mode'da şu an devre dışı.**
> `_diarize_local()`/pyannote.audio uçtan uca doğrulandı ve çalışıyor
> (aşağıdaki adımlar hâlâ geçerli, kod silinmedi), ama hedef deploy ortamı
> (VPS, GPU yok) için Whisper'ın üzerine pyannote'un CPU maliyeti kabul
> edilemez derecede yüksek çıktı — bu yüzden endpoint artık onu hiç
> çağırmıyor, `diarized_text` local mode'da her zaman `null` döner. Yeniden
> açmak için `backend/server.py`'de `transcribe_audio()` içindeki, yorum
> satırına alınmış `_diarize_local`/`_align_and_format_diarization` çağrı
> bloğunun yorumunu kaldırın (bkz. kod yorumu). API mode (Claude ile
> diarization) bundan etkilenmedi, aynı şekilde çalışmaya devam ediyor.

**1) Hugging Face token alın (manuel, siz yapmalısınız):**
1. https://huggingface.co adresinde hesap oluşturun/giriş yapın.
2. https://huggingface.co/pyannote/speaker-diarization-3.1 sayfasına gidip
   kullanım şartlarını kabul edin ("Agree and access repository").
3. **Ayrıca** https://huggingface.co/pyannote/speaker-diarization-community-1
   sayfasının şartlarını da kabul edin — `speaker-diarization-3.1` pipeline'ı
   arka planda bu modeli de indiriyor (pyannote.audio 4.x ile eklenen bir
   bağımlılık); sadece ilkini kabul etmek yeterli değil, token'ınız
   `403 GatedRepoError` ile reddedilir. Bunu bu projeyi gerçek bir token'la
   test ederken böyle keşfettik — pyannote'un kendi dokümantasyonu bunu açıkça
   vurgulamıyor.
4. https://huggingface.co/settings/tokens üzerinden "Read" yetkili bir token
   oluşturun, `backend/.env`'e `HF_TOKEN=hf_...` olarak yapıştırın.

**2) `.env`'i ayarlayın ve çalıştırın:**
```bash
cd backend
# backend/.env içinde:
#   TRANSCRIPTION_BACKEND=local
#   HF_TOKEN=hf_...              (1. adımdaki token)
#   WHISPER_MODEL_SIZE=small     (opsiyonel — tiny/base/small/medium/large-v3)
#   WHISPER_BATCH_SIZE=8         (opsiyonel — bkz. BENCHMARK.md)
.venv/bin/pip install -r requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
.venv/bin/uvicorn server:app --reload
```
İlk `/api/transcribe` isteğinde faster-whisper modeli ve pyannote pipeline
ağırlıkları `~/.cache/huggingface`'e indirilir (birkaç yüz MB — internet
gerekir); sonraki çalıştırmalar bu cache'i kullanır, network gerekmez.
CPU üzerinde int8 quantization ve batching (`BatchedInferencePipeline`) ile
çalışır — GPU gerekmez ama `small`/`medium` modelleri ile transkripsiyon API
moduna göre belirgin şekilde daha yavaştır. Hangi `WHISPER_MODEL_SIZE`'ın
sizin donanımınız/ses kaliteniz için doğru olduğuna karar vermeden önce
**`BENCHMARK.md`**'ye bakın — 4 çekirdekli bir ortamda ölçülen hız/model
boyutu karşılaştırması orada.

Yukarıdaki HF_TOKEN adımları diarization şu an kapalıyken de geçerli:
`TRANSCRIPTION_BACKEND=local` fail-fast mantığı hâlâ `HF_TOKEN` bekliyor
(ileride tekrar açılabilmesi için bilinçli olarak kaldırılmadı — bkz.
yukarıdaki devre dışı bırakma notu).

**Her istekte hız/doğruluk seçimi (`quality_mode`):** `/api/transcribe`'a
opsiyonel bir form alanı gönderebilirsiniz — `quality_mode=standard`
(varsayılan, `WHISPER_MODEL_SIZE`'ı kullanır) veya `quality_mode=precise`
(her zaman `large-v3-turbo`, env'den bağımsız — ~3x daha yavaş ama bazı
zor/gürültülü kayıtlarda daha doğru, bkz. `BENCHMARK.md` "Bulgu 4"). Frontend
bunu "Hızlı (standart)" / "Hassas" iki buton olarak sunuyor, varsayılan
Hızlı. İki model de aynı anda belleğe yüklenmez — her biri sadece fiilen
talep edildiğinde yüklenip cache'lenir, aynı moddaki sonraki istekler
yeniden yükleme maliyeti ödemez.

Diarization yeniden açıldığında geçerli olacak davranış (kod hazır, aşağıdaki
gibi uçtan uca doğrulandı): pipeline yüklenemez/başarısız olursa istek
**başarısız olmaz** — `_diarize_with_claude`'un API-mode'daki davranışıyla
aynı: hata loglanır, `diarized_text: null` ile düz transkript dönülür. Ses,
pyannote'a dosya yolu yerine `av` ile kendi decode ettiğimiz bir waveform
olarak veriliyor, bu yüzden diarization için sistemde ayrıca ffmpeg kurulu
olması gerekmiyor (Docker image'ında zaten var). Gerçek bir HF token ve
birden fazla konuşmacı içeren bir kayıtla uçtan uca doğru "1. kişi / 2. kişi"
çıktısı üretildiği manuel olarak test edildi — bkz. `memory/PRD.md` changelog.

## Test Çalıştırma

**Backend** (`backend/`): `.venv` + `pytest`.
```bash
cd backend
# .venv kurulumu ve backend'i ayağa kaldırma için "Kurulum" bölümüne bakın.
.venv/bin/uvicorn server:app --reload &
REACT_APP_BACKEND_URL=http://127.0.0.1:8000 API_KEY=<.env'deki değer> \
  .venv/bin/pytest tests/backend_test.py -v
```
Gerçek Whisper/Claude API çağrısı gerektiren testler (`@pytest.mark.skip`,
`REQUIRES_REAL_API`) `EMERGENT_LLM_KEY` olmadan otomatik atlanır.

`POST /api/transcribe` artık `X-API-Key` header'ı gerektiriyor (`.env`'deki
`API_KEY` ile eşleşmeli, yoksa 401) ve IP başına 5/dakika ile sınırlı (aşılırsa
429 — bkz. `SECURITY_NOTES.md`). `GET /api/`, `GET /api/health` açık kalır.

**Frontend** (`frontend/`): CRA/craco + Jest + React Testing Library.
```bash
cd frontend
# .env kurulumu için "Kurulum" bölümüne bakın.
yarn install
yarn test              # izleme modu
CI=true yarn test --watchAll=false   # tek seferlik, CI modu
```
Testler `src/pages/Transcriber.test.jsx` içinde: render, dosya seçimi/
validasyonu, backend hata/başarı yanıtı senaryoları (`src/setupTests.js`
jest-dom matcher'larını yükler).

**CI**: `.github/workflows/ci.yml`, push/PR'da backend pytest + frontend
`yarn test`'i otomatik çalıştırır (GitHub Actions).

## API Endpoint'leri

`/api` prefix'li, tümü [`backend/server.py`](backend/server.py) içinde tanımlı.

| Method | Path | Auth | Açıklama |
|---|---|---|---|
| GET | `/api/` | — | Karşılama mesajı |
| GET | `/api/health` | — | Sağlık kontrolü |
| POST | `/api/transcribe` | `X-API-Key` + rate limit (5/dk) | Dosya yükle → transkribe et (+ opsiyonel diarization) |

## Desteklenen Dosya Formatları

Tam liste `backend/server.py`'de (`WHISPER_NATIVE_EXTS`/`EXTRA_AUDIO_EXTS`/
`VIDEO_EXTS`/`DVR_EXTS`) — özet:

- **Ses:** mp3, wav, m4a, aac, ogg, opus, wma, aiff, amr, ac3, au, caf, mp2 …
- **Video (ses otomatik ayıklanır):** mp4, mov, avi, mkv, webm, wmv, flv,
  3gp, ts, mpg …
- **DVR/güvenlik kamerası:** `.dav` (Dahua ve benzeri DVR'lar) — **best-effort,
  garanti değil.** Bu format genelde H.264 video + G.711/G.726 ses codec'i
  içeriyor, ffmpeg/libav çoğunlukla decode edebiliyor ama garantili değil;
  codec desteklenmiyorsa net bir 400 hatası alırsınız ("VLC ile standart bir
  formata dönüştürün").
- **Desteklenmeyen:** `.flac` — bilinçli olarak dışarıda (bkz. `memory/PRD.md`
  backlog, CLAUDE.md "Bilinen Kritik Sorunlar" madde 4).

Uzantı tek başına yeterli değil: her yükleme, transkripsiyona geçmeden önce
`_verify_media_stream()` ile gerçekten decode edilebilir bir ses akışı içerip
içermediği açısından da kontrol ediliyor (PyAV/libav ile — sistemde ayrıca
`ffprobe` binary'si gerekmiyor). Uzantı doğru ama içerik bozuk/decode
edilemezse (özellikle `.dav`'de olası), jenerik "desteklenmiyor" yerine
içeriğe özel bir 400 hatası dönülür.

## Daha Fazla Bilgi

- [`CLAUDE.md`](CLAUDE.md) — proje durumu, mimari, bilinen açık sorunlar,
  Claude Code alt ajanları için kurallar.
- [`memory/PRD.md`](memory/PRD.md) — ürün gereksinimleri, backlog,
  "Profesyonelleştirme Geçmişi" (tüm ajan değişikliklerinin günlüğü).
- [`SECURITY_NOTES.md`](SECURITY_NOTES.md) — auth/rate-limit değerlendirmesi
  ve implementasyon detayı.
- [`design_guidelines.json`](design_guidelines.json) — tasarım sistemi
  (renk, tipografi, layout kuralları).
