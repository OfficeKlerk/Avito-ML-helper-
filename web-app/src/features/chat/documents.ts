import { call, type Api, type Schemas } from "../../shared/api/client";

export function getDocument(api: Api, docId: string, signal: AbortSignal): Promise<Schemas["Document"]> {
  return call(api.GET("/api/knowledge/documents/{doc_id}", {
    params: { path: { doc_id: docId } }, signal, cache: "no-store",
  }));
}

export function sourceUrl({ doc_id, chunk_id }: Schemas["Source"]) {
  const prefix = doc_id + "#";
  const anchor = chunk_id.startsWith(prefix) ? chunk_id.slice(prefix.length) : "";
  return "/chat/sources/" + encodeURIComponent(doc_id) + (anchor ? "/" + encodeURIComponent(anchor) : "");
}

type Section = { anchor: string; title: string; lines: string[] };
const sectionHeading = /^ {0,3}##\s+(.+?)\s+\{#([a-z0-9_-]+)\}\s*$/;
const codeFence = /^ {0,3}(`{3,}|~{3,})(.*)$/;

// The knowledge service uses explicit anchors on level-two headings. Fenced examples are content.
export function splitDocument(text: string) {
  const sections: Section[] = [];
  const intro: string[] = [];
  let lines = intro;
  let fence: string | undefined;

  for (const line of text.split(/\r?\n/)) {
    const marker = codeFence.exec(line);
    if (fence) {
      lines.push(line);
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = undefined;
      continue;
    }
    if (marker) fence = marker[1];
    const heading = sectionHeading.exec(line);
    if (heading) {
      lines = [];
      sections.push({ title: heading[1], anchor: heading[2], lines });
    } else {
      lines.push(line);
    }
  }

  const introduction = intro.join("\n").trim().replace(/^#\s+[^\n]*(?:\n|$)/, "").trim();
  return { introduction, sections };
}

const documentDate = new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeZone: "UTC" });

export function formatDocumentDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : documentDate.format(date);
}
