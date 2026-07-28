# Alt Ajan Görevi: infra-agent

> Önce CLAUDE.md dosyasını oku. Bu görevi test-agent tamamlandıktan SONRA
> çalıştır. CLAUDE.md'deki "Mevcut Mimari" bölümündeki "Deploy: Yok" durumunu
> kapsar.

## Görev Kapsamı

### 1. Dockerfile'lar
- `backend/Dockerfile`: Python 3.11+ slim base image, ffmpeg kurulumu (pydub
  ffmpeg'e bağımlı — bunu unutma, aksi halde ses işleme container içinde
  çalışmaz), requirements.txt kurulumu, uvicorn ile başlatma.
- `frontend/Dockerfile`: Multi-stage build — build stage'de `npm run build`,
  serve stage'de Nginx ile statik dosyaları sun.

### 2. docker-compose.yml
Kök dizinde, şu servisleri tanımla:
- `backend` (yukarıdaki Dockerfile'dan)
- `frontend` (yukarıdaki Dockerfile'dan)
- `mongodb` — SADECE cleanup-agent MongoDB'yi kullanmaya devam etme kararı
  aldıysa ekle; MongoDB kaldırıldıysa bu servisi ekleme.
- Ortam değişkenlerini `.env` dosyasından okuyacak şekilde yapılandır
  (docker-compose `env_file` direktifi).

### 3. Nginx config (frontend için)
- Statik dosya sunumu + `/api` isteklerini backend container'ına reverse
  proxy ile yönlendiren temel bir `nginx.conf`.
- LGS platformundaki mevcut Nginx/SSL deneyimini referans al (varsa benzer
  bir config kalıbı kullanılabilir) ama bu projenin kendi domain/SSL
  gereksinimlerine göre ayrı bir config olmalı, LGS'ninkiyle karıştırılmamalı.

### 4. CI/CD (opsiyonel, GitHub Actions)
- Basit bir `.github/workflows/ci.yml`: push/PR'da backend pytest'leri ve
  frontend testlerini (test-agent'ın kurduğu) otomatik çalıştıran bir pipeline.
- Bu adım opsiyonel — eğer proje sahibi henüz GitHub Actions kullanmayacaksa
  atla, sadece not düş.

## Kısıtlar
- `pytest.ini` içindeki `addopts`'a dokunma.
- Mevcut `test_fixtures/` klasöründeki örnek ses dosyalarını CI/test
  ortamında kullanılabilir şekilde referansla.

## Teslim
İşin sonunda şunları özetle:
- Oluşturulan dosyaların listesi (Dockerfile'lar, docker-compose.yml,
  nginx.conf, varsa CI dosyası).
- `docker-compose up` ile projenin ayağa kalkıp kalkmadığının doğrulaması.
- MongoDB servisi eklendi mi, eklenmediyse neden.
