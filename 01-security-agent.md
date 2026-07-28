# Alt Ajan Görevi: security-agent

> Önce CLAUDE.md dosyasını oku. Bu görev CLAUDE.md'deki "Bilinen Kritik
> Sorunlar" listesinin 1, 2, 5 ve 7. maddelerini kapsar.

## Görev Kapsamı

### 1. CORS düzeltmesi
`backend/server.py` içindeki CORS middleware yapılandırmasını bul.
Şu anki hali `allow_origins=['*']` + `allow_credentials=True` — bu kombinasyon
tarayıcı CORS spesifikasyonuna göre geçersiz/riskli.

Düzelt:
- `CORS_ORIGINS` env değişkeninden gelen değeri virgülle ayrılmış bir liste
  olarak parse et (örn. `"http://localhost:3000,https://app.example.com"`).
- Eğer `CORS_ORIGINS` tanımlı değilse, güvenli bir default kullan (localhost'a
  sınırla), `'*'` kullanma.
- `allow_credentials=True` kalacaksa, `allow_origins` kesinlikle spesifik
  domain listesi olmalı, wildcard olamaz.

### 2. Env değişkeni hata yönetimi
`os.environ['MONGO_URL']` ve `os.environ['DB_NAME']` gibi doğrudan indeksleme
kullanılan yerleri bul.

Düzelt:
- `os.environ.get('MONGO_URL')` kullan, `None` dönerse uygulama başlangıcında
  anlaşılır bir hata mesajıyla (hangi env değişkeninin eksik olduğunu belirten)
  net bir exception fırlat — sessiz KeyError yerine.
- Eğer bu görevi yaparken MongoDB'nin gerçekten kullanılıp kullanılmadığını
  görürsen ama KALDIRMA — bu karar `cleanup-agent` görevinde, PRD.md'de
  gerekçelendirilerek alınacak. Şimdilik sadece hata yönetimini düzelt.

### 3. Sessiz hata yutma
`_diarize_with_claude()` fonksiyonundaki `except Exception: return None` bloğunu bul.

Düzelt:
- Exception'ı logla (mevcut logging altyapısını kullan, print() ekleme).
- Hangi hatanın oluştuğunu (exception mesajı) log'a yaz.
- Kullanıcıya dönen davranış aynı kalabilir (None dönüp diarization'sız devam
  etmek makul bir fallback), ama artık production'da sorun teşhis edilebilir olmalı.

### 4. Auth/yetkilendirme — DEĞERLENDİRME (henüz implementasyon değil)
Bu adımda auth EKLEME. Sadece:
- Mevcut 3 endpoint'in (`/`, `/health`, `/transcribe`) hangi risk seviyesinde
  olduğunu değerlendir (örn. `/transcribe` maliyetli bir API çağrısı tetikliyor,
  rate-limit veya auth olmadan kötüye kullanılabilir).
- Kısa bir not olarak `memory/PRD.md`'ye veya ayrı bir `SECURITY_NOTES.md`
  dosyasına, auth eklenmesi gerektiğini ve önerilen yaklaşımı (API key header'ı
  mı, JWT mi, rate-limiting mi) yaz. Bu, ayrı bir orchestrator kararı olarak
  ele alınacak.

## Kısıtlar
- `pytest.ini` içindeki `addopts`'a dokunma.
- Mevcut `/api` prefix konvansiyonunu koru.
- Her değişiklikten sonra `backend/tests/backend_test.py` çalıştır, sonucu raporla.

## Teslim
İşin sonunda şunları özetle:
- Hangi dosyalarda ne değişti (kısa liste).
- Test sonucu (kaç test geçti/kaldı).
- Auth için yazdığın değerlendirme notunun özeti.
