import { useCallback, useMemo, useRef, useState } from "react";
import axios from "axios";
import { AnimatePresence, motion } from "framer-motion";
import {
  UploadCloud,
  FileAudio,
  Copy,
  Download,
  AlertCircle,
  Loader2,
  RotateCcw,
  Waves,
  CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const ALLOWED_EXT = ["mp3", "wav", "m4a", "webm", "mp4", "mpeg", "mpga"];
const MAX_SIZE_MB = 25;

const formatBytes = (bytes) => {
  if (!bytes && bytes !== 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
};

const getExt = (name = "") => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");

export default function Transcriber() {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | uploading | done | error
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState(null); // {text, language, filename, size_bytes}
  const [error, setError] = useState(null);
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);

  const validateAndSetFile = useCallback((f) => {
    if (!f) return;
    const ext = getExt(f.name);
    if (!ALLOWED_EXT.includes(ext)) {
      toast.error("Desteklenmeyen dosya formatı", {
        description: `.${ext || "?"} desteklenmiyor. Kabul edilen: ${ALLOWED_EXT.join(", ")}`,
      });
      return;
    }
    if (f.size > MAX_SIZE_MB * 1024 * 1024) {
      toast.error("Dosya çok büyük", {
        description: `Maksimum ${MAX_SIZE_MB} MB. Yüklenen: ${formatBytes(f.size)}`,
      });
      return;
    }
    setFile(f);
    setResult(null);
    setError(null);
    setStatus("idle");
    setProgress(0);
  }, []);

  const onSelect = (e) => {
    const f = e.target.files?.[0];
    validateAndSetFile(f);
    // Reset input value so selecting same file re-triggers change
    e.target.value = "";
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    validateAndSetFile(f);
  };

  const startTranscription = async () => {
    if (!file) return;
    setStatus("uploading");
    setProgress(0);
    setError(null);
    setResult(null);

    const form = new FormData();
    form.append("file", file);
    form.append("language", "tr");

    try {
      const res = await axios.post(`${API}/transcribe`, form, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (evt) => {
          if (evt.total) {
            // Upload phase up to 70%, remainder simulates processing
            const uploadPct = Math.round((evt.loaded / evt.total) * 70);
            setProgress(uploadPct);
          }
        },
        timeout: 180000,
      });
      // Simulate processing tick to 95, then complete
      setProgress(95);
      setResult(res.data);
      setStatus("done");
      setProgress(100);
      toast.success("Transkripsiyon tamamlandı");
    } catch (err) {
      const detail =
        err?.response?.data?.detail ||
        err?.message ||
        "Bilinmeyen bir hata oluştu.";
      setError(detail);
      setStatus("error");
      toast.error("Transkripsiyon başarısız", { description: detail });
    }
  };

  const resetAll = () => {
    setFile(null);
    setResult(null);
    setError(null);
    setStatus("idle");
    setProgress(0);
  };

  const copyText = async () => {
    if (!result?.text) return;
    try {
      await navigator.clipboard.writeText(result.text);
      toast.success("Panoya kopyalandı");
    } catch {
      toast.error("Kopyalanamadı");
    }
  };

  const downloadTxt = () => {
    if (!result?.text) return;
    const blob = new Blob([result.text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const base = (result.filename || "transkripsiyon").replace(/\.[^.]+$/, "");
    a.download = `${base}.txt`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast.success("İndirildi", { description: `${base}.txt` });
  };

  const wordCount = useMemo(() => {
    if (!result?.text) return 0;
    return result.text.trim().split(/\s+/).filter(Boolean).length;
  }, [result]);

  const charCount = result?.text?.length || 0;

  return (
    <div className="min-h-screen w-full bg-[#FAFAFA] text-[#111827]">
      {/* Header */}
      <header className="border-b border-black/10 bg-[#FAFAFA]/95 backdrop-blur sticky top-0 z-30">
        <div className="max-w-5xl mx-auto px-4 md:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-black text-white flex items-center justify-center hard-shadow-sm">
              <Waves className="w-5 h-5" strokeWidth={2.5} />
            </div>
            <div className="leading-tight">
              <div className="font-display font-black text-lg tracking-tight" data-testid="app-title">
                SesDeşifre
              </div>
              <div className="tech-label">Ses → Metin Dönüştürücü</div>
            </div>
          </div>
          <div
            className="hidden md:inline-flex items-center gap-2 px-3 py-1.5 border border-black/20 bg-white"
            data-testid="feature-badge"
          >
            <span className="w-1.5 h-1.5 bg-[#002FA7]" />
            <span className="tech-label !text-[10px] !text-black">
              Düşük Frekans Optimizasyonu · Aktif
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 md:px-6 py-12 md:py-20">
        {/* Hero */}
        <section className="mb-10">
          <div className="tech-label mb-4">V1 · Whisper Motoru</div>
          <h1 className="font-display font-black text-4xl sm:text-5xl lg:text-6xl tracking-tight leading-[1.02]">
            Kalitesiz sesleri
            <br />
            <span className="inline-block bg-black text-white px-2 py-0.5">temiz metne</span> dönüştürün.
          </h1>
          <p className="mt-6 max-w-xl text-base leading-relaxed text-gray-600">
            Düşük frekanslı, gürültülü veya kalitesiz kayıtları yükleyin. Sistem,
            konuşmayı yüksek doğrulukla Türkçe metne çevirir. Hesap gerekmez.
          </p>
        </section>

        {/* Dropzone */}
        <AnimatePresence mode="wait">
          {status === "idle" && !file && (
            <motion.div
              key="dropzone"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
            >
              <label
                htmlFor="audio-input"
                data-testid="upload-dropzone"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    inputRef.current?.click();
                  }
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={onDrop}
                className={`focus-ring block cursor-pointer border-2 border-dashed p-12 md:p-16 text-center bg-white transition-all ${
                  dragOver
                    ? "border-black bg-black/[0.04]"
                    : "border-black/25 hover:border-black hover:bg-black/[0.03]"
                }`}
              >
                <div className="mx-auto w-14 h-14 bg-black text-white flex items-center justify-center mb-6">
                  <UploadCloud className="w-7 h-7" />
                </div>
                <div className="font-display font-bold text-xl md:text-2xl tracking-tight mb-2">
                  Ses dosyasını buraya sürükleyin
                </div>
                <div className="text-sm text-gray-600 mb-6">
                  veya seçmek için tıklayın
                </div>
                <div className="inline-flex items-center gap-2 border border-black/15 bg-[#FAFAFA] px-3 py-1.5">
                  <span className="tech-label !text-[10px]">Desteklenen</span>
                  <span className="font-mono text-xs">
                    {ALLOWED_EXT.slice(0, 6).join(" · ")}
                  </span>
                </div>
                <div className="mt-3 tech-label !text-[10px]">
                  Maksimum boyut · {MAX_SIZE_MB} MB
                </div>
                <input
                  ref={inputRef}
                  id="audio-input"
                  data-testid="audio-input"
                  type="file"
                  accept="audio/*,.mp3,.wav,.m4a,.webm,.mp4,.mpeg,.mpga"
                  className="hidden"
                  onChange={onSelect}
                />
              </label>
            </motion.div>
          )}

          {/* Selected file / Uploading */}
          {file && status !== "done" && (
            <motion.div
              key="selected"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="bg-white border border-black/10 p-6 md:p-8 hard-shadow-sm"
              data-testid="selected-file-panel"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-4 min-w-0">
                  <div className="w-11 h-11 bg-black text-white flex items-center justify-center flex-shrink-0">
                    <FileAudio className="w-5 h-5" />
                  </div>
                  <div className="min-w-0">
                    <div
                      className="font-display font-bold text-base md:text-lg truncate"
                      data-testid="selected-filename"
                    >
                      {file.name}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                      <span className="tech-label">Boyut · {formatBytes(file.size)}</span>
                      <span className="tech-label">
                        Format · .{getExt(file.name)}
                      </span>
                    </div>
                  </div>
                </div>
                {status === "idle" && (
                  <button
                    onClick={resetAll}
                    className="tech-label hover:text-black underline underline-offset-4 decoration-black/30 hover:decoration-black"
                    data-testid="change-file-btn"
                  >
                    Değiştir
                  </button>
                )}
              </div>

              {/* Progress bar */}
              {status === "uploading" && (
                <div className="mt-8" data-testid="progress-panel">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin text-[#002FA7]" />
                      <span className="tech-label !text-black">
                        Ses işleniyor · Gürültü azaltma & düşük frekans iyileştirme
                      </span>
                    </div>
                    <span className="font-mono text-sm" data-testid="progress-percent">
                      {progress}%
                    </span>
                  </div>
                  <div className="h-2 w-full bg-black/10 overflow-hidden">
                    <motion.div
                      className="h-full bg-[#002FA7]"
                      initial={{ width: 0 }}
                      animate={{ width: `${progress}%` }}
                      transition={{ duration: 0.4, ease: "easeOut" }}
                    />
                  </div>
                </div>
              )}

              {status === "error" && (
                <div className="mt-6 border border-[#FF3B30] bg-[#FFF5F4] p-4 flex items-start gap-3" data-testid="error-panel">
                  <AlertCircle className="w-5 h-5 text-[#FF3B30] flex-shrink-0 mt-0.5" />
                  <div className="text-sm">
                    <div className="font-semibold text-[#B32218]">Bir hata oluştu</div>
                    <div className="text-gray-700 mt-1 break-words">{error}</div>
                  </div>
                </div>
              )}

              <div className="mt-8 flex flex-wrap gap-3">
                <button
                  onClick={startTranscription}
                  disabled={status === "uploading"}
                  className="bg-black text-white px-6 py-3 font-medium hover:bg-gray-800 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  data-testid="start-transcribe-btn"
                >
                  {status === "uploading" ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Dönüştürülüyor…
                    </>
                  ) : (
                    <>
                      <Waves className="w-4 h-4" />
                      Metne Dönüştür
                    </>
                  )}
                </button>
                {status !== "uploading" && (
                  <button
                    onClick={resetAll}
                    className="border border-black text-black px-6 py-3 font-medium hover:bg-gray-100 transition-colors flex items-center gap-2"
                    data-testid="cancel-btn"
                  >
                    <RotateCcw className="w-4 h-4" />
                    Vazgeç
                  </button>
                )}
              </div>
            </motion.div>
          )}

          {/* Result */}
          {status === "done" && result && (
            <motion.div
              key="result"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="bg-white border border-black/10 p-6 md:p-8 hard-shadow"
              data-testid="result-panel"
            >
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 bg-[#002FA7] text-white flex items-center justify-center">
                    <CheckCircle2 className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="font-display font-bold text-lg tracking-tight">
                      Transkripsiyon Tamamlandı
                    </div>
                    <div className="tech-label mt-0.5">
                      {wordCount} kelime · {charCount} karakter
                    </div>
                  </div>
                </div>
                <button
                  onClick={resetAll}
                  className="tech-label hover:text-black underline underline-offset-4 decoration-black/30 hover:decoration-black"
                  data-testid="new-file-btn"
                >
                  ↺ Yeni Dosya
                </button>
              </div>

              <div
                aria-live="polite"
                data-testid="transcription-text"
                className="mt-6 leading-relaxed text-[15px] text-gray-800 max-h-[52vh] overflow-y-auto custom-scrollbar text-left whitespace-pre-wrap break-words border-l-2 border-black/10 pl-4"
              >
                {result.text || (
                  <span className="text-gray-500 italic">
                    (Ses içerisinde metne çevrilebilir konuşma bulunamadı.)
                  </span>
                )}
              </div>

              <div className="flex flex-wrap justify-end gap-3 mt-6 border-t border-black/10 pt-5">
                <button
                  onClick={copyText}
                  className="border border-black text-black px-5 py-2.5 font-medium hover:bg-gray-100 transition-colors flex items-center gap-2"
                  data-testid="copy-btn"
                >
                  <Copy className="w-4 h-4" />
                  Panoya Kopyala
                </button>
                <button
                  onClick={downloadTxt}
                  className="bg-black text-white px-5 py-2.5 font-medium hover:bg-gray-800 transition-colors flex items-center gap-2"
                  data-testid="download-btn"
                >
                  <Download className="w-4 h-4" />
                  TXT Olarak İndir
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Info footer */}
        <section className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-6" data-testid="info-section">
          {[
            {
              n: "01",
              t: "Kalitesiz Ses",
              d: "Düşük frekans, gürültü ve fısıltı içeren kayıtları destekler.",
            },
            {
              n: "02",
              t: "Çoklu Format",
              d: "mp3, wav, m4a, webm, mp4 — hepsi tek arayüzden.",
            },
            {
              n: "03",
              t: "Gizlilik",
              d: "Dosyalar yalnızca transkripsiyon için işlenir, saklanmaz.",
            },
          ].map((x) => (
            <div key={x.n} className="border-t-2 border-black pt-4">
              <div className="tech-label">{x.n}</div>
              <div className="font-display font-bold text-lg mt-1">{x.t}</div>
              <div className="text-sm text-gray-600 mt-2 leading-relaxed">{x.d}</div>
            </div>
          ))}
        </section>
      </main>

      <footer className="border-t border-black/10 py-6 mt-10">
        <div className="max-w-5xl mx-auto px-4 md:px-6 flex flex-wrap justify-between items-center gap-2">
          <div className="tech-label">SesDeşifre · Whisper v1</div>
          <div className="tech-label">© {new Date().getFullYear()}</div>
        </div>
      </footer>
    </div>
  );
}
