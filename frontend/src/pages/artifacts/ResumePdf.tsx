import { Document, Font, Page, Text, View, pdf } from "@react-pdf/renderer";
import type { ResumeDocument } from "@/api/careerWorkspace";

Font.register({
  family: "NotoSC",
  src: `${import.meta.env.BASE_URL}fonts/NotoSansSC-Regular.ttf`,
});
// Empty syllables create zero-width break glue without changing the text.
// Splitting into plain syllables alone makes textkit insert English hyphens.
Font.registerHyphenationCallback((word) =>
  /\p{Script=Han}/u.test(word)
    ? (word.match(/\p{Script=Han}|[^\p{Script=Han}]+/gu) ?? [word]).flatMap(
        (part) => [part, ""],
      )
    : [word],
);
const colors = { forest: "#476c4a", slate: "#394957", blue: "#356587" };
export async function buildResumePdf(data: ResumeDocument, title: string) {
  const accent = colors[data.accent];
  return pdf(
    <Document title={title} author={data.name} language="zh-CN">
      <Page
        size="A4"
        style={{
          fontFamily: "NotoSC",
          fontSize: data.font_size,
          padding: 40,
          color: "#333b32",
        }}
      >
        <View
          style={{
            paddingBottom: 18,
            borderBottomWidth: 2,
            borderBottomColor: accent,
            marginBottom: 18,
            ...(data.template === "modern"
              ? { backgroundColor: "#f1f4ed", padding: 18 }
              : {}),
          }}
          wrap={false}
        >
          <Text
            style={{
              fontSize: 26,
              lineHeight: 1.4,
              color: accent,
              marginBottom: 8,
            }}
          >
            {data.name || title}
          </Text>
          {!!data.headline && (
            <Text style={{ fontSize: 12, lineHeight: 1.6 }}>
              {data.headline}
            </Text>
          )}
          {!!data.contact && (
            <Text
              style={{
                fontSize: 9,
                lineHeight: 1.5,
                color: "#747d6f",
                marginTop: 8,
              }}
            >
              {data.contact}
            </Text>
          )}
        </View>
        {!!data.summary && (
          <Text style={{ marginBottom: 12 }}>{data.summary}</Text>
        )}
        {data.sections.map((section) => (
          <View key={section.id} style={{ marginBottom: 16 }}>
            <Text
              minPresenceAhead={45}
              style={{
                color: accent,
                fontSize: data.font_size + 2,
                borderBottomWidth: 0.5,
                borderBottomColor: "#dfe5d8",
                paddingBottom: 5,
                marginBottom: 8,
              }}
            >
              {section.title}
            </Text>
            <Text orphans={2} widows={2}>
              {section.content}
            </Text>
          </View>
        ))}
        <Text
          fixed
          render={({ pageNumber, totalPages }) =>
            `${pageNumber} / ${totalPages ?? pageNumber}`
          }
          style={{
            position: "absolute",
            bottom: 18,
            left: 40,
            right: 40,
            textAlign: "center",
            fontSize: 8,
            color: "#9ba48e",
          }}
        >
          1
        </Text>
      </Page>
    </Document>,
  ).toBlob();
}

export async function exportResumePdf(data: ResumeDocument, title: string) {
  const blob = await buildResumePdf(data, title);
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = `${title.replace(/[\\/:*?"<>|]/g, "_")}.pdf`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 3000);
}
