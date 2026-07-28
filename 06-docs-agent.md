# Alt Ajan Görevi: docs-agent

> Önce CLAUDE.md dosyasını oku. Bu görevi EN SON çalıştır — tüm diğer
> ajanlar tamamlandıktan sonra, çünkü dokümantasyon gerçek son duruma göre
> yazılmalı. CLAUDE.md'deki "Bilinen Kritik Sorunlar" listesinin 9. maddesini
> kapsar.

## Görev Kapsamı

### 1. README.md
Kök dizindeki placeholder README'yi gerçek içerikle doldur:
- Proje açıklaması (ne yapıyor, kim için)
- Mimari özeti (backend/frontend/DB, kısa diagram veya madde listesi)
- Kurulum adımları:
  - Backend: virtualenv, `pip install -r requirements.txt`, gerekli env
    değişkenleri, `uvicorn server:app` ile çalıştırma
  - Frontend: `npm install`, `npm start`
  - Docker ile: `docker-compose up` (infra-agent'ın kurduğu)
- Test çalıştırma: backend (`pytest`) ve frontend (test-agent'ın kurduğu
  komut) için ayrı talimatlar
- API endpoint özeti (mevcut 3 endpoint, kısa tablo)

### 2. .env.example dosyaları
- `backend/.env.example`: `MONGO_URL`, `DB_NAME` (cleanup-agent kararına göre
  hâlâ gerekliyse), `EMERGENT_LLM_KEY`, `CORS_ORIGINS` — her biri için kısa
  açıklama yorum satırı olarak.
- `frontend/.env.example`: `REACT_APP_BACKEND_URL` ve varsa craco ile ilgili
  diğer değişkenler.

### 3. PRD.md güncellemesi
`memory/PRD.md` içine, tüm ajanların yaptığı değişiklikleri özetleyen bir
"Profesyonelleştirme Geçmişi" bölümü ekle (tarih + hangi ajan + ne değişti).
Bu, projenin gelecekteki geliştiricileri (veya gelecekteki Claude Code
oturumları) için bir değişiklik günlüğü işlevi görecek.

### 4. CLAUDE.md güncellemesi
CLAUDE.md dosyasındaki "Bilinen Kritik Sorunlar" listesini gözden geçir —
çözülmüş maddeleri "Çözüldü" olarak işaretle veya listeden çıkar, hâlâ açık
olanları (örn. FLAC/OGG server-side transcoding P2 backlog'a bırakıldıysa)
güncel durumuyla bırak.

## Kısıtlar
- Var olan `design_guidelines.json` içeriğini README'de tekrar etme, sadece
  referans ver.
- Emergent platformuna özgü (`.emergent/`) dosyaları README'de detaylandırma,
  sadece varlığından ve amacından kısaca bahset.

## Teslim
İşin sonunda şunları özetle:
- Yazılan/güncellenen dosyaların listesi.
- README'nin yeni bir geliştiricinin projeyi sıfırdan ayağa kaldırması için
  yeterli olup olmadığına dair kendi değerlendirmen.
