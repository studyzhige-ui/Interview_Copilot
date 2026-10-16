import { useEffect, useState } from "react";
import { buildResumePdf } from "./ResumePdf";
import type { ResumeDocument } from "@/api/careerWorkspace";
import { extractErr } from "@/api/client";

export default function PdfPreview({
  data,
  title,
}: {
  data: ResumeDocument;
  title: string;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const serialized = JSON.stringify(data);
  useEffect(() => {
    let cancelled = false,
      objectUrl = "";
    const timer = setTimeout(() => {
      void buildResumePdf(JSON.parse(serialized), title)
        .then((blob) => {
          if (cancelled) return;
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
          setError("");
        })
        .catch((cause) => {
          if (!cancelled) setError(extractErr(cause));
        });
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [serialized, title]);
  return error ? (
    <p role="alert">{error}</p>
  ) : url ? (
    <iframe
      title="PDF 分页预览"
      src={`${url}#toolbar=0&view=FitH`}
      className="w-full min-h-[850px] border-0"
    />
  ) : (
    <p className="career-muted">正在生成分页预览…</p>
  );
}
