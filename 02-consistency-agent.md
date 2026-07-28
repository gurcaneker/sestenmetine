# Alt Ajan Görevi: consistency-agent

> Önce CLAUDE.md dosyasını oku. Bu görev CLAUDE.md'deki "Bilinen Kritik
> Sorunlar" listesinin 3 ve 4. maddelerini kapsar.

## Görev Kapsamı

### 1. Dosya boyutu limiti tutarsızlığı
Şu an üç farklı yerde üç farklı değer var:
- Frontend (`src/pages/Transcriber.jsx` veya ilgili validasyon dosyası): 40MB
- Backend (`backend/server.py`): 500MB
- `memory/PRD.md`: 25MB

Yap:
- Whisper API'nin gerçek dosya boyutu limitini (`_prepare_chunks()` fonksiyonundaki
  20MB parça mantığına bak — bu muhtemelen Whisper'ın 25MB limitine göre
  ayarlanmış) doğrula.
- Tek bir gerçek limite karar ver (muhtemelen PRD.md'deki 25MB doğru olan,
  çünkü Whisper API sınırına en yakın olan bu).
- Bu tek değeri bir yerde sabit olarak tanımla (backend'de bir config/constants
  dosyası, frontend'de de aynı değere referans veren bir constant).
- Frontend ve backend'deki üç farklı sayıyı bu tek kaynağa göre güncelle.
- Kullanıcıya gösterilen hata mesajlarının da güncel limiti doğru yansıttığından
  emin ol.

### 2. FLAC/OGG format tutarsızlığı
`backend/tests/backend_test.py` içinde bu tutarsızlık zaten dokümante edilmiş:
backend FLAC/OGG'u destekliyormuş gibi ilan ediyor ama altta Whisper wrapper
bu formatları reddedip 500 + ham provider hatası dönüyor.

İki seçenekten birini uygula (hangisini seçtiğini gerekçelendir):

**Seçenek A (kısa vadede önerilen):** Desteklenmeyen formatlar listesinden
FLAC/OGG'u çıkar, kullanıcıya net bir "desteklenmeyen format" hatası dön
(500 yerine 400 + anlaşılır mesaj).

**Seçenek B (PRD.md'deki P2 backlog'una uygun):** Server-side transcoding
ekle (pydub zaten ffmpeg kullanıyor, FLAC/OGG'u WAV/MP3'e transcode edip
Whisper'a öyle gönder). Bu daha büyük bir iş — eğer bu seçeneği uygularsan,
bunu ayrı bir görev olarak işaretle ve orchestrator'a bildir, tek başına
consistency-agent kapsamında bitirme.

Varsayılan olarak Seçenek A'yı uygula, Seçenek B'yi PRD.md'nin backlog
kısmına not düş.

## Kısıtlar
- `pytest.ini` içindeki `addopts`'a dokunma.
- Var olan test dosyasındaki FLAC hata testini (mevcut davranışı doğrulayan)
  yeni davranışa göre güncelle, silme.

## Teslim
İşin sonunda şunları özetle:
- Karar verilen tek dosya boyutu limiti ve nerede tanımlandığı.
- FLAC/OGG için hangi seçeneğin uygulandığı ve gerekçesi.
- Test sonucu (kaç test geçti/kaldı).
