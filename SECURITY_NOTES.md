# Güvenlik Notları

> security-agent görevi kapsamında oluşturuldu (değerlendirme).
> **2026-07-23: UYGULANDI.** Orchestrator kararı: basit API-key header +
> rate limiting (JWT/çok-kullanıcılı sistem YOK — bkz. `memory/PRD.md`
> Architecture bölümü). Aşağıdaki "Öneri" bölümü artık geçmiş kayıt; gerçek
> implementasyon "Uygulama Durumu" bölümünde.

## Endpoint risk değerlendirmesi

| Endpoint | Risk seviyesi | Gerekçe |
|---|---|---|
| `GET /api/` | Düşük | Statik karşılama mesajı, yan etkisi yok. |
| `GET /api/health` | Düşük | Durum bilgisi dışında veri sızdırmıyor. |
| `POST /api/transcribe` | **Yüksek** | Kimliksiz/limitsiz olarak çağrılabiliyor. Her çağrı OpenAI Whisper (ve genellikle Claude diarization) API'lerine maliyetli istek gönderiyor, 500 MB'a kadar dosya kabul ediyor. Auth veya rate-limit olmadan: (1) maliyet istismarına (üçüncü şahıslar API kotasını/faturasını tüketebilir), (2) DoS'a (büyük dosyalarla sunucu kaynaklarını/ffmpeg transcode sürecini tüketme), (3) veri sızıntısına (herkes herhangi bir ses dosyasını yükleyip transkript alabilir) açık. |

## Öneri

`/api/transcribe` için, öncelik sırasıyla:

1. **Rate limiting** (kısa vadede en düşük efor / en yüksek fayda): IP başına
   dakika/saat bazlı istek sınırı (örn. `slowapi` / `fastapi-limiter` + Redis
   veya basit in-memory sliding window). Maliyetli API çağrılarını istismara
   karşı en hızlı koruyan önlem budur.
2. **API key header'ı** (orta vadede): İstemcinin `X-API-Key` header'ı ile
   sunucu tarafında tanımlı bir veya birkaç anahtarla eşleşmesini zorunlu
   kılmak. Kullanıcı yönetimi gerektirmez, tek-kullanıcılı/dahili kullanım
   için yeterli olabilir.
3. **JWT tabanlı auth** (proje çok-kullanıcılı hale gelirse): Kullanıcı
   modeli, login/register akışı ve token doğrulaması gerektirir — şu anki
   MVP kapsamı için fazla ağır; PRD.md'de çok-kullanıcılı senaryo netleşirse
   değerlendirilmeli.

Kısa vadede (1) rate limiting + (2) basit API key kombinasyonu, mimariye
büyük bir ek yapmadan `/transcribe` endpoint'ini kötüye kullanıma karşı
makul ölçüde korur. Bu, ayrı bir orchestrator kararı/görevi olarak ele
alınmalı — bu doküman sadece değerlendirmeyi kayıt altına alıyor.

## Uygulama Durumu (2026-07-23)

**API-key header** — `backend/server.py`, `require_api_key()`:
- `.env`'den okunan tek bir `API_KEY` değeri (uygulama başlangıcında zorunlu,
  yoksa `RuntimeError` ile net mesajla çöker — diğer zorunlu env değişkenleriyle
  aynı desen).
- `POST /api/transcribe` isteğinde `X-API-Key` header'ı bu değerle eşleşmeli;
  eşleşmezse `401` + `"Geçersiz veya eksik API anahtarı (X-API-Key)."`.
- `GET /api/`, `GET /api/health` korumasız kaldı (düşük risk, statik yanıt —
  bkz. yukarıdaki risk tablosu).
- FastAPI route-level `dependencies=[Depends(require_api_key)]` olarak
  uygulandı — bu, rate limit kontrolünden (aşağıda) ÖNCE çalışır: yanlış/eksik
  anahtarlı istekler rate-limit bütçesini tüketmez.

**Rate limiting** — `backend/server.py`, `slowapi` (`Limiter`, `@limiter.limit`):
- **Limit: IP başına 5 istek/dakika**, sadece `POST /api/transcribe` üzerinde
  (`RATE_LIMIT` sabiti, `server.py`'nin üst kısmında — değiştirmek isterseniz
  hem oradaki sabiti hem bu satırı güncelleyin).
- Aşılırsa `429` + Türkçe mesaj (`_rate_limit_handler`, slowapi'nin varsayılan
  İngilizce mesajı yerine).
- **⚠️ Depolama: in-memory, tek process (infra-agent için — Docker/deployment
  kararında dikkate alınmalı):** `slowapi`'nin varsayılan depolama backend'i
  process-local in-memory bir sayaç. Mevcut tek-instance/tek-worker deploy
  için doğru çalışır, ama uygulama birden fazla worker/instance ile (örn.
  uvicorn `--workers N>1`, gunicorn+uvicorn worker'ları, veya birden fazla
  container/replica arkasında bir load balancer) yatay ölçeklenirse, HER
  worker kendi ayrı sayacını tutar — bir istemci farklı worker'lara
  dağıtıldığında gerçek limit görünürde `N × 5/dakika`'ya çıkar (örn. 4
  worker = fiilen 20/dakika), bu da rate limitin amacını (maliyetli
  Whisper/Claude çağrılarını istismara karşı korumak) zayıflatır. Docker
  Compose/K8s ile çoklu-instance bir deploy planlanıyorsa, `slowapi`'nin
  Redis storage backend'ine (`storage_uri="redis://..."`) geçilmeli —
  tüm worker/instance'lar arasında paylaşılan tek bir sayaç sağlar.
- 5/dakika değeri orchestrator kararıyla seçildi (bkz. görev talimatı);
  kullanım verisi toplandıkça değiştirilebilir — ilk aday: gerçek kullanıcı
  şikayeti/istismar deseni gözlemlendiğinde.

**Test kapsamı** — `backend/tests/backend_test.py`, `TestTranscribeAuthAndRateLimit`:
missing/wrong API key → 401, rate limit aşımı → 429 + Türkçe mesaj. Mevcut
`TestTranscribeValidation` testleri `AUTH_HEADERS` ile güncellendi (401 yerine
kendi asıl senaryolarını test etmeye devam ediyorlar).

**Kapsam dışı bırakılanlar (bilinçli):** JWT, kullanıcı hesabı/login,
API key rotasyonu/çoklu-anahtar desteği, admin paneli. Proje tek-kullanıcılı/
dahili kullanım için tasarlanıyor; bu ihtiyaç değişirse yeniden değerlendirilmeli
(bkz. `memory/PRD.md`).

## Local mode notu (2026-07-28)

`TRANSCRIPTION_BACKEND=local` (bkz. `memory/PRD.md`) **gizlilik açısından
olumlu**: ses dosyaları hiç OpenAI/Anthropic'e gönderilmiyor, tamamen sunucuda
işleniyor — hassas/gizli içerik işleyen kullanıcılar için bu bir avantaj.

Yeni bir sır: `HF_TOKEN` (Hugging Face access token). `backend/.env`'de
diğer sırlarla (`API_KEY`, `EMERGENT_LLM_KEY`) aynı şekilde tutuluyor, aynı
şekilde `.gitignore`'da. Rate limiting/auth davranışı local modda **değişmiyor**
— `/api/transcribe` hâlâ aynı `X-API-Key` + 5/dakika limitine tabi, backend
seçimi bu katmanın altında, şeffaf bir şekilde çalışıyor.
