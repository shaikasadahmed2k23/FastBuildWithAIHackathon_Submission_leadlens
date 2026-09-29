"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import * as React from "react";

import { CitationChip } from "@/components/inspector";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { api, type ImportPreview, type ImportResult } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

/** CSV import: choose file -> confirm column mapping -> see what was imported and rejected. */
export function ImportSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<ImportPreview | null>(null);
  const [mapping, setMapping] = React.useState<Record<string, string | null>>({});
  const [result, setResult] = React.useState<ImportResult | null>(null);
  const qc = useQueryClient();

  const reset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setMapping({});
  };

  const previewM = useMutation({
    mutationFn: api.importPreview,
    onSuccess: (p) => {
      setPreview(p);
      setMapping(p.mapping);
    },
  });
  const importM = useMutation({
    mutationFn: () => api.importCsv(file!, mapping, "reviewer"),
    onSuccess: (r) => {
      setResult(r);
      for (const key of [["overview"], ["leads"], ["health"]]) qc.invalidateQueries({ queryKey: key });
    },
  });

  const hasIdentity = !!(mapping.email || mapping.first_name || mapping.last_name);
  const canImport = !!preview && !!mapping.company && hasIdentity && !importM.isPending;

  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) reset();
      }}
      title="Import leads from CSV"
      description="HubSpot, Salesforce and similar exports. Nothing is written until you confirm the mapping."
      className="max-w-[760px]"
    >
      <div className="space-y-5 p-4">
        {result ? (
          <ImportSummary result={result} onAnother={reset} />
        ) : (
          <>
            <label className="flex cursor-pointer items-center justify-center gap-2 rounded border border-dashed border-zinc-300 px-4 py-6 text-sm text-zinc-600 hover:border-zinc-400 hover:bg-zinc-50">
              <Upload className="size-4" />
              {file ? (
                <span>
                  <span className="font-medium text-zinc-900">{file.name}</span> · {fmt.int(file.size / 1024)} KB · choose
                  another
                </span>
              ) : (
                "Choose a .csv file"
              )}
              <input
                type="file"
                accept=".csv,text/csv"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setFile(f);
                    setPreview(null);
                    previewM.mutate(f);
                  }
                }}
              />
            </label>

            {previewM.isPending ? <p className="text-sm text-zinc-500">Reading file…</p> : null}
            {previewM.isError ? <ErrorState error={previewM.error} /> : null}

            {preview ? (
              <>
                <section>
                  <h3 className="mb-2 text-xs font-medium text-zinc-500">
                    Column mapping · {fmt.int(preview.rows)} rows
                  </h3>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                        <th className="py-1.5 pr-3 font-normal">LeadLens field</th>
                        <th className="py-1.5 pr-3 font-normal">CSV column</th>
                        <th className="py-1.5 font-normal">Sample (normalized)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.keys(preview.labels).map((field) => {
                        const required = field === "company";
                        const sample = preview.sample[0]?.[field];
                        return (
                          <tr key={field} className="border-b border-zinc-100">
                            <td className="py-1 pr-3">
                              {preview.labels[field]}
                              {required ? <span className="ml-1 text-red-600">*</span> : null}
                            </td>
                            <td className="py-1 pr-3">
                              <Select
                                value={mapping[field] ?? ""}
                                onChange={(e) => setMapping((m) => ({ ...m, [field]: e.target.value || null }))}
                                className={cn("h-7 w-56 text-xs", !mapping[field] && "text-zinc-400")}
                                aria-label={`CSV column for ${preview.labels[field]}`}
                              >
                                <option value="">Not mapped</option>
                                {preview.headers.map((h) => (
                                  <option key={h} value={h}>
                                    {h}
                                  </option>
                                ))}
                              </Select>
                            </td>
                            <td className="max-w-[220px] truncate py-1 font-mono text-xs text-zinc-600">
                              {mapping[field] === preview.mapping[field] && sample != null ? String(sample) : ""}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {preview.unmapped_headers.length ? (
                    <p className="mt-2 text-2xs text-zinc-500">Ignored columns: {preview.unmapped_headers.join(", ")}</p>
                  ) : null}
                  {!hasIdentity ? (
                    <p className="mt-2 text-xs text-red-700">Map Email or a name column so leads can be identified.</p>
                  ) : null}
                </section>

                {preview.will_reject ? (
                  <section>
                    <h3 className="mb-2 text-xs font-medium text-zinc-500">
                      {preview.will_reject} rows will be rejected (with the proposed mapping)
                    </h3>
                    <RejectedList rows={preview.rejections} />
                  </section>
                ) : null}

                <div className="flex items-center justify-end gap-2 border-t border-zinc-200 pt-4">
                  {importM.isError ? (
                    <span className="mr-auto text-xs text-red-700">
                      {importM.error instanceof Error ? importM.error.message : "Import failed"}
                    </span>
                  ) : null}
                  <Button variant="ghost" onClick={reset}>
                    Cancel
                  </Button>
                  <Button variant="primary" disabled={!canImport} onClick={() => importM.mutate()}>
                    {importM.isPending ? "Importing…" : `Import ${fmt.int(preview.rows - preview.will_reject)} rows`}
                  </Button>
                </div>
              </>
            ) : null}
          </>
        )}
      </div>
    </Sheet>
  );
}

function RejectedList({ rows }: { rows: { row: number; reasons: string[] }[] }) {
  return (
    <ul className="max-h-48 divide-y divide-zinc-100 overflow-y-auto rounded border border-zinc-200 text-xs">
      {rows.map((r) => (
        <li key={r.row} className="flex gap-3 px-3 py-1.5">
          <span className="tnum w-14 shrink-0 font-mono text-zinc-500">row {r.row}</span>
          <span className="text-zinc-800">{r.reasons.join("; ")}</span>
        </li>
      ))}
    </ul>
  );
}

function ImportSummary({ result, onAnother }: { result: ImportResult; onAnother: () => void }) {
  const stats: [string, number][] = [
    ["Imported", result.imported],
    ["Rejected", result.rejected.length],
    ["New companies", result.new_companies],
    ["Matched companies", result.matched_companies],
  ];
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-px overflow-hidden rounded border border-zinc-200 bg-zinc-200">
        {stats.map(([label, value]) => (
          <div key={label} className="bg-white px-3 py-2">
            <div className="text-2xs text-zinc-500">{label}</div>
            <div className="tnum text-lg font-semibold">{fmt.int(value)}</div>
          </div>
        ))}
      </div>
      <section>
        <h3 className="mb-2 text-xs font-medium text-zinc-500">Cleaning ran on the imported leads</h3>
        <ul className="space-y-1 text-sm">
          <li>
            <span className="tnum font-mono">{result.issues.duplicate}</span> involved in duplicates (within the file or
            with existing leads)
          </li>
          <li>
            <span className="tnum font-mono">{result.issues.stale}</span> stale
          </li>
          <li>
            <span className="tnum font-mono">{result.issues.missing_field}</span> missing email, phone or title
          </li>
        </ul>
      </section>
      {result.lead_ids.length ? (
        <section>
          <h3 className="mb-2 text-xs font-medium text-zinc-500">Imported leads (first 12)</h3>
          <div className="flex flex-wrap gap-1">
            {result.lead_ids.slice(0, 12).map((id) => (
              <CitationChip key={id} id={id} />
            ))}
          </div>
        </section>
      ) : null}
      {result.rejected.length ? (
        <section>
          <h3 className="mb-2 text-xs font-medium text-zinc-500">Rejected rows</h3>
          <RejectedList rows={result.rejected} />
        </section>
      ) : null}
      {result.warnings.length ? (
        <p className="text-2xs text-zinc-500">
          {result.warnings.length} {result.warnings.length === 1 ? "warning" : "warnings"}, e.g. row{" "}
          {result.warnings[0].row}: {result.warnings[0].message}
        </p>
      ) : null}
      <div className="flex justify-between border-t border-zinc-200 pt-4 text-2xs text-zinc-500">
        <span>
          Logged as <span className="font-mono">{result.batch_id}</span> in the audit log.
        </span>
        <Button size="sm" onClick={onAnother}>
          Import another file
        </Button>
      </div>
    </div>
  );
}
