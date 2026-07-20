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
- Desteklenen formatlar: mp3, wav, m4a, webm, mp4, mpeg, mpga (Whisper resmi listesi)
- Max 25 MB
- Düşük kaliteli / düşük frekans seslere uygun (Whisper + gürültü işleme prompt)
- Metin sonucu görüntüleme + Panoya kopyala + TXT indir
- Hesap yok, geçmiş yok

## Architecture
- **Frontend**: React (CRA) + Tailwind + shadcn/ui + framer-motion + sonner
- **Backend**: FastAPI (`/api/transcribe`), `emergentintegrations.llm.openai.OpenAISpeechToText` (whisper-1)
- **DB**: MongoDB (mevcut, MVP için kullanılmıyor)
- **Env**: `EMERGENT_LLM_KEY` (universal key)

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
- **P1**: 25 MB üstü dosyalar için client-side veya server-side ffmpeg ile parçalama
- **P2**: FLAC/OGG için sunucu-tarafı transcoding (şu an desteklenmiyor)
- **P2**: Otomatik dil algılama seçeneği (şu an sabit `tr`)
- **P2**: Kayıt geçmişi (opsiyonel; hesap gerektirir)
- **P2**: Tarayıcıda mikrofon kaydı → doğrudan transkripsiyon

## Next Tasks
1. Kullanıcı geri bildirimi topla; en çok istenen özelliği belirle
2. Zaman damgaları + SRT indirme (P1)
3. Büyük dosya parçalama (P1)
