// Report export: downloads the committed comparison report as JSON or Markdown.
// `?format=md` returns the shareable Markdown; anything else returns the raw
// JSON artifact (the exact bytes CI gates on).
import { loadExampleReport, reportToMarkdown } from "@/lib/evals";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const report = loadExampleReport();
  if (!report) {
    return new Response("No committed report found.", { status: 404 });
  }
  const format = new URL(request.url).searchParams.get("format");
  if (format === "md") {
    return new Response(reportToMarkdown(report), {
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition": 'attachment; filename="crucible-comparison.md"',
      },
    });
  }
  return new Response(JSON.stringify(report, null, 2), {
    headers: {
      "Content-Type": "application/json",
      "Content-Disposition": 'attachment; filename="crucible-comparison.json"',
    },
  });
}
