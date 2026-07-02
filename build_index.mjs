// Builds a static Pagefind index from records.jsonl (one record per OCR'd page).
// Output: demo/pagefind/  -> upload that folder to S3 for production.
import * as pagefind from "pagefind";
import fs from "node:fs";
import readline from "node:readline";

const IN = process.argv[2] || "records.jsonl";
const OUT = process.argv[3] || "demo/pagefind";

const { index } = await pagefind.createIndex({});
let n = 0, withText = 0;

const rl = readline.createInterface({ input: fs.createReadStream(IN) });
for await (const line of rl) {
  if (!line.trim()) continue;
  const r = JSON.parse(line);
  const m = r.meta;
  const content = (r.content || "").trim();
  if (content.length > 20) withText++;
  // The body we index = the OCR text; we also fold in the issue name + date so
  // filename/date searches hit even on pages where OCR is weak.
  const body = `${m.paper} — ${m.date_label} (page ${r.page})\n\n${content}`;
  await index.addCustomRecord({
    url: r.url,
    content: body,
    language: "en",
    meta: {
      title: `${m.paper} — ${m.date_label}`,
      page: String(r.page),
      collection: m.collection,
      date: m.date_label,
      image: "", // (could point to a thumbnail later)
    },
    filters: {
      paper: [m.paper],
      decade: [m.decade].filter(Boolean),
      year: [m.year].filter(Boolean),
    },
    sort: { date: m.sortkey, page: String(r.page).padStart(3, "0") },
  });
  n++;
  if (n % 5000 === 0) {
    const rss = Math.round(process.memoryUsage().rss / 1048576);
    console.log(`  added ${n} pages… (node rss ${rss} MB)`);
  }
}

console.log(`all ${n} pages added; writing index files…`);
await index.writeFiles({ outputPath: OUT });
console.log(`indexed ${n} pages (${withText} with usable OCR text) -> ${OUT}`);
process.exit(0);
