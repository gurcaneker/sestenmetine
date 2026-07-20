import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import Transcriber from "@/pages/Transcriber";

function App() {
  return (
    <BrowserRouter>
      <Toaster
        position="top-center"
        toastOptions={{
          style: {
            borderRadius: 0,
            border: "1px solid #000",
            background: "#fff",
            color: "#111827",
            fontFamily: "'IBM Plex Sans', sans-serif",
          },
        }}
      />
      <Routes>
        <Route path="/" element={<Transcriber />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
