import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axios from "axios";
import Transcriber from "./Transcriber";

// framer-motion's real animation lifecycle isn't relevant to these tests and
// adds act()/timer noise in jsdom — swap motion.* / AnimatePresence for
// plain passthrough elements that drop the animation-only props.
jest.mock("framer-motion", () => {
  const React = require("react");
  const stripMotionProps = ({
    initial, animate, exit, transition, whileHover, whileTap, layout, variants,
    ...rest
  }) => rest;
  const passthrough = (tag) => {
    const Component = React.forwardRef((props, ref) =>
      React.createElement(tag, { ref, ...stripMotionProps(props) }, props.children)
    );
    Component.displayName = `motion.${tag}`;
    return Component;
  };
  return {
    motion: new Proxy({}, { get: (_target, tag) => passthrough(tag) }),
    AnimatePresence: ({ children }) => React.createElement(React.Fragment, null, children),
  };
});

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock("axios");

const selectFile = async (file) => {
  const input = screen.getByTestId("audio-input");
  await userEvent.upload(input, file);
};

const makeFile = (name, content = "dummy audio bytes", type = "audio/mpeg") =>
  new File([content], name, { type });

describe("<Transcriber />", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("hatasız render olur ve yükleme alanını gösterir", () => {
    render(<Transcriber />);
    expect(screen.getByTestId("app-title")).toHaveTextContent("SesDeşifre");
    expect(screen.getByTestId("upload-dropzone")).toBeInTheDocument();
  });

  it("desteklenen bir dosya seçildiğinde seçili-dosya paneline geçer", async () => {
    render(<Transcriber />);
    await selectFile(makeFile("kayit.mp3"));

    expect(await screen.findByTestId("selected-file-panel")).toBeInTheDocument();
    expect(screen.getByTestId("selected-filename")).toHaveTextContent("kayit.mp3");
    // Dropzone yerini seçili-dosya paneline bırakmış olmalı
    expect(screen.queryByTestId("upload-dropzone")).not.toBeInTheDocument();
  });

  it("desteklenmeyen formatta dosya seçildiğinde dosyayı reddeder (seçili panel açılmaz)", async () => {
    const { toast } = require("sonner");
    render(<Transcriber />);
    // fireEvent (not userEvent.upload) on purpose: userEvent.upload silently
    // no-ops for files that don't match the input's `accept` attribute (real
    // browser file-picker behavior). validateAndSetFile()'s own extension
    // check is what's actually under test here — it's the defense-in-depth
    // path also hit by onDrop, which has no such browser-level filtering.
    const input = screen.getByTestId("audio-input");
    fireEvent.change(input, { target: { files: [makeFile("notes.txt", "hello", "text/plain")] } });

    expect(toast.error).toHaveBeenCalledWith(
      "Desteklenmeyen dosya formatı",
      expect.objectContaining({ description: expect.stringContaining(".txt") })
    );
    expect(screen.queryByTestId("selected-file-panel")).not.toBeInTheDocument();
    expect(screen.getByTestId("upload-dropzone")).toBeInTheDocument();
  });

  it("backend 400/500 hatası döndüğünde kullanıcıya sunucudan gelen mesajı gösterir", async () => {
    axios.post.mockRejectedValueOnce({
      response: { data: { detail: "Desteklenmeyen dosya formatı: .flac" } },
    });

    render(<Transcriber />);
    await selectFile(makeFile("kayit.mp3"));
    await userEvent.click(screen.getByTestId("start-transcribe-btn"));

    const errorPanel = await screen.findByTestId("error-panel");
    expect(errorPanel).toHaveTextContent("Desteklenmeyen dosya formatı: .flac");
    expect(screen.queryByTestId("result-panel")).not.toBeInTheDocument();
  });

  it("transcribe isteğine X-API-Key header'ını ekler (REACT_APP_API_KEY'den)", async () => {
    // frontend/.env.test REACT_APP_API_KEY=test-fixture-api-key tanımlar (CRA
    // bunu NODE_ENV=test'te otomatik yükler) — Transcriber.jsx bunu modül
    // yüklenirken okuyor, bu yüzden değeri burada değil .env.test'te set ediyoruz.
    axios.post.mockResolvedValueOnce({ data: { text: "ok", filename: "kayit.mp3" } });

    render(<Transcriber />);
    await selectFile(makeFile("kayit.mp3"));
    await userEvent.click(screen.getByTestId("start-transcribe-btn"));

    await screen.findByTestId("result-panel");
    expect(axios.post).toHaveBeenCalledWith(
      expect.stringContaining("/transcribe"),
      expect.anything(),
      expect.objectContaining({
        headers: expect.objectContaining({ "X-API-Key": "test-fixture-api-key" }),
      })
    );
  });

  it("backend başarılı yanıt döndüğünde sonuç panelini gösterir", async () => {
    axios.post.mockResolvedValueOnce({
      data: {
        text: "Merhaba dünya",
        diarized_text: null,
        language: "tr",
        filename: "kayit.mp3",
        size_bytes: 123,
        chunks: 1,
      },
    });

    render(<Transcriber />);
    await selectFile(makeFile("kayit.mp3"));
    await userEvent.click(screen.getByTestId("start-transcribe-btn"));

    const resultPanel = await screen.findByTestId("result-panel");
    expect(resultPanel).toBeInTheDocument();
    expect(screen.getByTestId("transcription-text")).toHaveTextContent("Merhaba dünya");
  });
});
