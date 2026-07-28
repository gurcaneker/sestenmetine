# Alt Ajan Görevi: test-agent

> Önce CLAUDE.md dosyasını oku. Bu görevi cleanup-agent tamamlandıktan
> SONRA çalıştır. CLAUDE.md'deki "Bilinen Kritik Sorunlar" listesinin 8.
> maddesini kapsar.

## Görev Kapsamı

### 1. Backend testlerini genişlet
Mevcut `backend/tests/backend_test.py` içinde 7 test var (root/health,
validasyon hataları, gerçek Whisper API çağrısıyla JFK örneği, FLAC hata
davranışı). Bunlara ek olarak:

- security-agent'ın CORS düzeltmesi için bir test ekle (yanlış origin'den
  gelen isteğin reddedildiğini doğrulayan).
- security-agent'ın env değişkeni hata yönetimi için bir test ekle (MONGO_URL
  eksikken uygulamanın anlaşılır bir hatayla başlangıçta durduğunu doğrulayan).
- consistency-agent'ın dosya boyutu limiti değişikliği için bir test ekle
  (yeni tek limitin doğru uygulandığını doğrulayan).
- consistency-agent'ın FLAC/OGG davranış değişikliği için mevcut testi
  güncelledi mi kontrol et, eksikse tamamla.

### 2. Frontend'e temel test altyapısı kur
Şu an frontend'de HİÇ test dosyası yok. CRA zaten Jest + React Testing
Library ile geliyor (craco üzerinden), ekstra kurulum gerekmeyebilir —
önce kontrol et.

Yap:
- `frontend/src/pages/Transcriber.jsx` için en azından şu senaryoları
  kapsayan temel testler yaz:
  - Bileşen hatasız render oluyor mu
  - Dosya seçildiğinde (mock upload) doğru state değişimi oluyor mu
  - Hata durumunda (backend 400/500 dönünce) kullanıcıya doğru mesaj
    gösteriliyor mu
- Test çalıştırma komutunu (`npm test` veya `craco test`) doğrula ve
  README'ye not düşülmek üzere kaydet (docs-agent kullanacak).

## Kısıtlar
- `pytest.ini` içindeki `addopts`'a dokunma — yeni testler bu yapılandırmayla
  uyumlu şekilde eklenmeli (`-n 2 --dist loadscope` paralel çalıştırmayla
  çakışmayacak şekilde, örn. paylaşılan state'e bağımlı testlerden kaçın).
- Gerçek API çağrısı gerektiren testleri (JFK örneği gibi) bozmadan, yanlarına ekle.

## Teslim
İşin sonunda şunları özetle:
- Backend'e eklenen yeni testlerin listesi ve sonucu.
- Frontend'de kurulan test altyapısı ve yazılan testlerin listesi.
- Toplam test sayısı ve geçme/kalma durumu.
