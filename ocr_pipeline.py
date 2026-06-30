#!/usr/bin/env python3
"""
OCR pipeline for the Minster Historical Society newspaper archive.

Reads a JSON list of S3 keys, downloads each PDF (stream & discard -- nothing
piles up on disk), rasterizes every page, OCRs it with Tesseract, and emits one
search record per page to records.jsonl.

Reusable for the full corpus: just point --keys at a bigger key list.

Usage:
  python3 ocr_pipeline.py --keys pilot_keys.json --out records.jsonl --workers 8
"""
import argparse, json, os, re, sys, time, tempfile, subprocess, urllib.request, urllib.parse
from concurrent.futures import ProcessPoolExecutor, as_completed

BUCKET = "https://s3.amazonaws.com/archives.minsterhistoricalsociety.com"
DPI = 300

MONTHS = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}

def parse_meta(key):
    """Derive collection / year / paper / issue date from the S3 key path."""
    parts = key.split("/")
    collection = parts[1] if len(parts) > 2 else ""
    year = parts[2] if len(parts) > 3 and parts[2].isdigit() else ""
    fname = parts[-1].rsplit(".", 1)[0]
    # paper name = collection text after the "YYYY to YYYY - " prefix
    paper = re.sub(r"^\d{4}\s*to\s*\d{4}\s*-\s*", "", collection).strip()
    # try to extract a clean issue date like "Jan 16"
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})", fname)
    date_label, sortkey = "", f"{year}-00-00"
    if m:
        mon = m.group(1)[:3].lower()
        day = int(m.group(2))
        if mon in MONTHS:
            date_label = f"{m.group(1).title()} {day}, {year}"
            sortkey = f"{year}-{MONTHS[mon]:02d}-{day:02d}"
    return {
        "collection": collection,
        "paper": paper or "Newspaper",
        "year": year,
        "decade": f"{year[:3]}0s" if len(year) == 4 else "",
        "issue": fname,
        "date_label": date_label or fname,
        "sortkey": sortkey,
    }

def pdf_url(key):
    return f"{BUCKET}/{urllib.parse.quote(key)}"

def ocr_one(key):
    """Download one PDF into memory, OCR every page, return page records. Nothing
    touches disk -- the PDF bytes and per-page PNG are streamed straight to
    Tesseract via stdin (a separate process can't read our temp dir under sandbox)."""
    import fitz  # imported inside worker
    meta = parse_meta(key)
    url = pdf_url(key)
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    try:
        data = urllib.request.urlopen(url, timeout=120).read()
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        return {"key": key, "error": f"download/open: {e}", "recs": []}
    recs = []
    for i, page in enumerate(doc):
        try:
            png = page.get_pixmap(dpi=DPI).tobytes("png")
            out = subprocess.run(
                ["tesseract", "stdin", "stdout", "--psm", "1", "-l", "eng"],
                input=png, capture_output=True, env=env, timeout=180)
            text = out.stdout.decode("utf-8", "ignore")
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
        except Exception:
            text = ""
        recs.append({
            "key": key,
            "url": f"{url}#page={i+1}",
            "page": i + 1,
            "content": text,
            "meta": meta,
        })
    return {"key": key, "error": None, "recs": recs}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", required=True)
    ap.add_argument("--out", default="records.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--resume", action="store_true",
                    help="skip keys already present in --out and append")
    ap.add_argument("--shards", type=int, default=1, help="total number of shards (CI parallelism)")
    ap.add_argument("--shard", type=int, default=0, help="which shard this run handles (0-based)")
    ap.add_argument("--time-budget", type=int, default=0,
                    help="stop starting new docs after N seconds (0 = no limit); for CI job time caps")
    args = ap.parse_args()

    keys = json.load(open(args.keys))

    # shard: interleave so each shard gets a balanced mix of old (small) and modern (big) issues
    if args.shards > 1:
        keys = [k for i, k in enumerate(keys) if i % args.shards == args.shard]
        print(f"[shard] {args.shard+1}/{args.shards} -> {len(keys)} of this shard's documents", flush=True)

    # resume: skip any document already written to the output file
    done_keys = set()
    if args.resume and os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try: done_keys.add(json.loads(line).get("key"))
                except Exception: pass
        before = len(keys)
        keys = [k for k in keys if k not in done_keys]
        print(f"[resume] {len(done_keys)} docs already done; {len(keys)} of {before} remaining", flush=True)

    total = len(keys)
    print(f"[start] {total} documents, {args.workers} workers -> {args.out}", flush=True)

    done = pages = errors = 0
    t0 = time.time()
    stopped_early = False
    out_mode = "a" if (args.resume and os.path.exists(args.out)) else "w"
    with open(args.out, out_mode) as fout, ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(ocr_one, k): k for k in keys}
        for fut in as_completed(futs):
            r = fut.result()
            done += 1
            if r["error"]:
                errors += 1
                print(f"  [err {done}/{total}] {r['key'][-40:]}: {r['error']}", flush=True)
            else:
                for rec in r["recs"]:
                    fout.write(json.dumps(rec) + "\n")
                    pages += 1
            if done % 5 == 0 or done == total:
                print(f"  [{done}/{total}] docs, {pages} pages OCR'd, {errors} errors", flush=True)
            fout.flush()  # keep the file current so cache/resume captures progress on early stop
            if args.time_budget and (time.time() - t0) > args.time_budget:
                stopped_early = True
                print(f"[time-budget] hit {args.time_budget}s after {done} docs; stopping early (resume will continue)", flush=True)
                ex.shutdown(wait=False, cancel_futures=True)
                break
    state = "stopped-early" if stopped_early else "done"
    print(f"[{state}] {done} docs, {pages} pages, {errors} errors -> {args.out}", flush=True)
    # exit code 0 always (a partial pass is success for CI); the workflow re-runs to finish

if __name__ == "__main__":
    main()
