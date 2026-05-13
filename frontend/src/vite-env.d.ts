/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOCK_TRANSCRIBE?: string;
  readonly VITE_MOCK_ANALYSIS_SSE?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
