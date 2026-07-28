# Alt Ajan Görevi: cleanup-agent

> Önce CLAUDE.md dosyasını oku. Bu görevi security-agent tamamlandıktan
> SONRA çalıştır. CLAUDE.md'deki "Bilinen Kritik Sorunlar" listesinin 6.
> maddesini ve MongoDB kararını kapsar.

## Görev Kapsamı

### 1. Kullanılmayan bağımlılıkları temizle
`backend/requirements.txt` içinde şunlar var ama kod tabanında kullanılmıyor:
`stripe`, `python-jose`, `PyJWT`, `passlib`, `bcrypt`, `google-generativeai`,
`google-genai`, `boto3`.

Yap:
- Her paket için kod tabanında (`grep -r` ile) gerçekten kullanılmadığını
  doğrula (import edilmiyor mu, kontrol et).
- security-agent'ın auth değerlendirme notunu (`SECURITY_NOTES.md` veya
  PRD.md'deki not) oku — eğer auth yakında eklenecekse `python-jose`/`PyJWT`/
  `passlib`/`bcrypt` YAKINDA kullanılacak olabilir, bu durumda onları SİLME,
  bir yorum satırıyla "auth implementasyonu için ayrılmış, henüz kullanılmıyor"
  şeklinde işaretle.
- Gerçekten hiç kullanılmayacak olanları (`stripe`, `google-generativeai`,
  `google-genai`, `boto3`) requirements.txt'den çıkar.
- Temizlik sonrası `pip install -r requirements.txt` ile kurulumun hâlâ
  çalıştığını doğrula.

### 2. MongoDB kararı
MongoDB bağlanıyor ama hiç CRUD/model/koleksiyon kullanılmıyor.

Yap:
- `memory/PRD.md`'yi oku, MongoDB'nin gelecekte planlanan bir kullanımı var mı
  kontrol et (örn. kayıt geçmişi özelliği P2 backlog'ta var — bu MongoDB
  gerektirebilir).
- Eğer yakın vadede (P1 backlog) kullanılmayacaksa: bağlantı kodunu kaldır,
  bu kararı `memory/PRD.md`'ye bir not olarak ekle ("MongoDB bağlantısı X
  tarihinde kaldırıldı, sebep: kullanılmıyor, ileride kayıt geçmişi
  özelliğiyle birlikte yeniden eklenecek").
- Eğer P1'de kullanılacaksa: bağlantıyı koru ama en azından temel bir
  health-check'e (`/api/health` endpoint'i MongoDB bağlantısını da kontrol
  etsin) bağla, böylece "bağlı ama hiç kullanılmıyor" durumu en azından
  görünür/anlamlı hale gelsin.

## Kısıtlar
- `pytest.ini` içindeki `addopts`'a dokunma.
- Silme kararlarını PRD.md'de belgele, sessizce silme.

## Teslim
İşin sonunda şunları özetle:
- Hangi paketler silindi, hangileri "ayrılmış" olarak işaretlendi ve neden.
- MongoDB için verilen karar ve gerekçesi.
- Test sonucu (kaç test geçti/kaldı).
