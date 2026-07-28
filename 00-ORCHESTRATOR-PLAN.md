# Orchestrator Planı — SesteŞmetine Profesyonelleştirme

Bu dosya alt ajanların sırasını ve bağımlılıklarını tanımlar. Her ajan görevini
bitirdiğinde, sonucu orchestrator'a (Claude.ai sohbeti) özetle — bir sonraki
ajanın promptu buna göre ince ayar yapılabilir.

## Sıra ve Bağımlılıklar

```
1. security-agent      (bağımsız, İLK çalıştırılmalı)
2. consistency-agent   (bağımsız, security-agent ile paralel de olabilir)
3. cleanup-agent       ← security-agent'tan sonra
4. test-agent          ← cleanup-agent'tan sonra
5. infra-agent         ← test-agent'tan sonra
6. docs-agent          ← EN SON (tüm değişiklikler netleşince)
```

## Neden bu sıra?

- **Security önce:** CORS ve env-crash sorunları, üzerine test yazılacak
  "doğru" davranışı belirler. Önce düzeltilmezse testler yanlış baseline alır.
- **Consistency, security ile paralel:** Dosya boyutu/format sorunları
  security'den bağımsız, aynı anda ele alınabilir.
- **Cleanup, security'den sonra:** Bağımlılık temizliği (MongoDB kararı dahil)
  güvenlik katmanı netleşmeden yapılırsa, auth gibi ileride eklenecek
  paketleri (bcrypt, jose) yanlışlıkla silebiliriz.
- **Test, cleanup'tan sonra:** Kod tabanı sadeleşmeden test yazmak, silinecek
  kod için gereksiz test üretimine yol açar.
- **Infra, test'ten sonra:** Docker/CI kurulumu, testlerin CI'da çalışacağı
  varsayımıyla yapılmalı.
- **Docs en son:** README ve .env.example, tüm gerçek yapılandırma netleşince
  yazılmalı — yoksa hemen eskir.

## Kullanım

Her ajan dosyasını (`agents/01-security-agent.md` vb.) sırayla VS Code'da
Claude Code'a yapıştır. Ajan işini bitirince:

1. Değişen dosyaları ve test sonucunu gözden geçir.
2. Orchestrator'a (bu sohbet) kısa bir özet ver: ne değişti, ne kırıldı/kırılmadı.
3. Orchestrator bir sonraki ajanın promptunu gerekirse günceller.

## İlerleme Takibi

- [ ] 01 — security-agent
- [ ] 02 — consistency-agent
- [ ] 03 — cleanup-agent
- [ ] 04 — test-agent
- [ ] 05 — infra-agent
- [ ] 06 — docs-agent
