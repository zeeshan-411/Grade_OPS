import { useState } from "react";
import type { GradeSummary, StudentGradeRow } from "@/api/client";

const FLAG_COLOR: Record<string, string> = {
  UNREADABLE: "bg-red-100 text-red-800 ring-red-200",
  LOW_OCR_CONFIDENCE: "bg-amber-100 text-amber-800 ring-amber-200",
  LLM_PARSE_ERROR: "bg-red-100 text-red-800 ring-red-200",
  LLM_API_ERROR: "bg-red-100 text-red-800 ring-red-200",
  NEEDS_REVIEW: "bg-amber-100 text-amber-800 ring-amber-200",
  VERIFIED_APPROVED: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  VERIFIED_CORRECTED: "bg-blue-100 text-blue-800 ring-blue-200",
  MATH_CORRECTED: "bg-blue-100 text-blue-800 ring-blue-200",
};

function FlagBadge({ flag }: { flag: string }) {
  const cls = FLAG_COLOR[flag] ?? "bg-slate-100 text-slate-700 ring-slate-200";
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}
    >
      {flag}
    </span>
  );
}

function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(grades: StudentGradeRow[]): string {
  const header = [
    "student_id",
    "question_id",
    "criterion_id",
    "marks_awarded",
    "justification",
    "question_total",
    "question_max",
    "student_total",
    "verified",
    "question_flags",
  ];
  const rows: string[][] = [header];
  for (const g of grades) {
    for (const q of g.payload.question_grades) {
      for (const c of q.criterion_results) {
        rows.push([
          g.student_id,
          q.question_id,
          c.criterion_id,
          String(c.marks_awarded),
          c.justification.replace(/"/g, '""'),
          String(q.total_marks),
          String(q.max_marks),
          String(g.total_score),
          String(q.verified),
          q.flags.join("|"),
        ]);
      }
    }
  }
  return rows
    .map((r) => r.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(","))
    .join("\n");
}

export function GradesSection({
  summary,
  examIdentifier,
}: {
  summary: GradeSummary;
  examIdentifier: string;
}) {
  const { run, grades, total_students, total_score, max_possible, needs_review, verified } =
    summary;
  const pct = max_possible > 0 ? (total_score / max_possible) * 100 : 0;

  return (
    <section className="mt-6">
      <h2 className="text-base font-semibold text-ink">Results</h2>
      <p className="mt-1 text-xs text-ink-muted">
        Run started {new Date(run.started_at).toLocaleString()} ·{" "}
        {run.finished_at ? `finished ${new Date(run.finished_at).toLocaleString()}` : "in progress"}{" "}
        · status {run.status}
      </p>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Students" value={String(total_students)} />
        <Metric
          label="Total score"
          value={`${total_score.toFixed(0)} / ${max_possible.toFixed(0)}`}
          sub={`${pct.toFixed(0)}%`}
        />
        <Metric label="Verified" value={String(verified)} tone="emerald" />
        <Metric label="Needs review" value={String(needs_review)} tone="amber" />
      </div>

      {grades.length > 0 && (
        <>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() =>
                downloadFile(
                  `grades_${examIdentifier}.json`,
                  JSON.stringify(
                    grades.map((g) => g.payload),
                    null,
                    2,
                  ),
                  "application/json",
                )
              }
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50"
            >
              Download JSON
            </button>
            <button
              type="button"
              onClick={() =>
                downloadFile(`grades_${examIdentifier}.csv`, toCsv(grades), "text/csv")
              }
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50"
            >
              Download CSV
            </button>
          </div>

          <div className="mt-3 space-y-3">
            {grades.map((g) => (
              <StudentCard key={g.id} grade={g} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "emerald" | "amber";
}) {
  const toneCls =
    tone === "emerald"
      ? "text-emerald-700"
      : tone === "amber"
        ? "text-amber-700"
        : "text-ink";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${toneCls}`}>{value}</p>
      {sub && <p className="text-xs text-ink-muted">{sub}</p>}
    </div>
  );
}

function StudentCard({ grade }: { grade: StudentGradeRow }) {
  const [open, setOpen] = useState(false);
  const { student_id, total_score, max_possible, flags, payload } = grade;
  const pct = max_possible > 0 ? (total_score / max_possible) * 100 : 0;

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-slate-50"
      >
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm font-semibold text-ink">{student_id}</span>
          <span className="text-sm text-ink-soft">
            {total_score.toFixed(0)} / {max_possible.toFixed(0)} ({pct.toFixed(0)}%)
          </span>
        </div>
        <div className="flex items-center gap-2">
          {flags.map((f) => (
            <FlagBadge key={f} flag={f} />
          ))}
          <span className="text-xs text-ink-muted">{open ? "Hide" : "Details"}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-100 bg-slate-50/50 p-4">
          {payload.question_grades.map((q) => (
            <div key={q.question_id} className="mb-4 last:mb-0">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-ink">
                  {q.question_id} — {q.total_marks.toFixed(0)} / {q.max_marks.toFixed(0)}
                </p>
                <div className="flex items-center gap-2">
                  {q.verified && (
                    <span className="text-xs font-medium text-emerald-700">verified</span>
                  )}
                  {q.flags.map((f) => (
                    <FlagBadge key={f} flag={f} />
                  ))}
                </div>
              </div>
              {q.summary && (
                <p className="mt-1 text-sm italic text-ink-soft">{q.summary}</p>
              )}
              <ul className="mt-2 space-y-1 text-sm">
                {q.criterion_results.map((c) => (
                  <li key={c.criterion_id} className="flex gap-2">
                    <span className="font-mono text-xs text-ink-muted">{c.criterion_id}</span>
                    <span className="font-mono text-xs text-ink-soft">
                      {c.marks_awarded.toFixed(0)}
                    </span>
                    <span className="text-ink-soft">— {c.justification}</span>
                  </li>
                ))}
              </ul>
              {q.deduction_results.some((d) => d.applied) && (
                <div className="mt-2 text-sm">
                  <p className="font-medium text-ink-soft">Deductions applied:</p>
                  <ul className="ml-4 list-disc text-xs">
                    {q.deduction_results
                      .filter((d) => d.applied)
                      .map((d, i) => (
                        <li key={i}>
                          {d.condition}: <span className="font-mono">{d.penalty.toFixed(0)}</span>
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
