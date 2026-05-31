import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AxiosError } from "axios";
import {
  clearExamGrades,
  clearExamPdfs,
  deleteExam,
  getExam,
  getExamGrades,
  listExamPdfs,
  listPlagiarism,
  triggerGrading,
  uploadExamPdfs,
  type ExamDetail,
  type ExamPdf,
  type GradeSummary,
  type PlagiarismPair,
  type UploadSummary,
} from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { GradesSection } from "@/pages/GradesSection";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function ExamDetailPage() {
  const { examId } = useParams<{ examId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isInstructor = user?.role === "INSTRUCTOR";

  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [pdfs, setPdfs] = useState<ExamPdf[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [pending, setPending] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [lastSummary, setLastSummary] = useState<UploadSummary | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [grades, setGrades] = useState<GradeSummary | null>(null);
  const [grading, setGrading] = useState(false);
  const [gradeError, setGradeError] = useState<string | null>(null);

  const [plagiarism, setPlagiarism] = useState<PlagiarismPair[]>([]);

  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);

  const [manageBusy, setManageBusy] = useState<"resetGrades" | "deleteExam" | null>(null);
  const [manageError, setManageError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!examId) return;
    try {
      const [e, list, g, p] = await Promise.all([
        getExam(examId),
        listExamPdfs(examId),
        getExamGrades(examId),
        listPlagiarism(examId),
      ]);
      setExam(e);
      setPdfs(list);
      setGrades(g);
      setPlagiarism(p);
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setError(ax.response?.data?.detail ?? ax.message);
    }
  }, [examId]);

  async function doResetGrades() {
    if (!examId) return;
    if (
      !confirm(
        "Delete every grading run for this exam? This removes all student grades, TA reviews, and plagiarism flags. PDFs are kept.",
      )
    )
      return;
    setManageBusy("resetGrades");
    setManageError(null);
    try {
      await clearExamGrades(examId);
      await refresh();
      setGrades(null);
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setManageError(ax.response?.data?.detail ?? ax.message);
    } finally {
      setManageBusy(null);
    }
  }

  async function doDeleteExam() {
    if (!examId || !exam) return;
    if (
      !confirm(
        `Delete exam "${exam.exam_id}"?\n\nRemoves the rubric, all PDFs, grading runs, reviews, and plagiarism flags. Cannot be undone.`,
      )
    )
      return;
    setManageBusy("deleteExam");
    setManageError(null);
    try {
      await deleteExam(examId);
      navigate("/exams", { replace: true });
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setManageError(ax.response?.data?.detail ?? ax.message);
      setManageBusy(null);
    }
  }

  async function doClear() {
    if (!examId) return;
    if (!confirm("Delete every uploaded PDF for this exam? This cannot be undone.")) return;
    setClearing(true);
    setClearError(null);
    try {
      await clearExamPdfs(examId);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setClearError(ax.response?.data?.detail ?? ax.message);
    } finally {
      setClearing(false);
    }
  }

  async function doGrade() {
    if (!examId) return;
    setGrading(true);
    setGradeError(null);
    try {
      const summary = await triggerGrading(examId);
      setGrades(summary);
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setGradeError(ax.response?.data?.detail ?? ax.message);
    } finally {
      setGrading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [refresh]);

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    setPending(files);
    setLastSummary(null);
    setUploadError(null);
  }

  async function doUpload() {
    if (!examId || pending.length === 0) return;
    setUploading(true);
    setUploadError(null);
    try {
      const summary = await uploadExamPdfs(examId, pending);
      setLastSummary(summary);
      setPending([]);
      await refresh();
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setUploadError(ax.response?.data?.detail ?? ax.message);
    } finally {
      setUploading(false);
    }
  }

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <Link to="/exams" className="text-xs font-medium text-accent hover:underline">
          ← Back to exams
        </Link>
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <Link to="/exams" className="text-xs font-medium text-accent hover:underline">
        ← Back to exams
      </Link>

      {exam ? (
        <header className="mt-2 border-b border-slate-200 pb-6">
          <p className="text-xs font-mono text-ink-muted">{exam.exam_id}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">{exam.title}</h1>
          <p className="text-sm text-ink-muted">{exam.course}</p>
        </header>
      ) : (
        <p className="mt-4 text-sm text-ink-muted">Loading…</p>
      )}

      <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-base font-semibold text-ink">Upload student PDFs</h2>
        <p className="mt-1 text-sm text-ink-muted">
          One PDF per student. Filename convention:{" "}
          <code>{`{student_id}.pdf`}</code> — e.g. <code>STU001.pdf</code>.
          Legacy per-question filenames like <code>STU001_Q1.pdf</code> are
          still accepted.
        </p>

        <input
          type="file"
          accept="application/pdf,.pdf"
          multiple
          onChange={onPick}
          className="mt-3 block w-full text-sm text-ink-soft file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink-soft hover:file:bg-slate-200"
        />

        {pending.length > 0 && (
          <p className="mt-2 text-xs text-ink-muted">
            {pending.length} file{pending.length > 1 ? "s" : ""} ready —{" "}
            {pending.map((f) => f.name).join(", ")}
          </p>
        )}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            disabled={pending.length === 0 || uploading}
            onClick={doUpload}
            className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {uploading ? "Uploading…" : `Upload ${pending.length || ""} PDF${pending.length === 1 ? "" : "s"}`.trim()}
          </button>
        </div>

        {uploadError && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {uploadError}
          </div>
        )}

        {lastSummary && (
          <div className="mt-3 space-y-2 text-sm">
            <p className="text-emerald-800">
              Uploaded {lastSummary.uploaded.length} file
              {lastSummary.uploaded.length === 1 ? "" : "s"}.
            </p>
            {lastSummary.rejected.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
                <p className="font-medium">Rejected:</p>
                <ul className="ml-4 list-disc text-xs">
                  {lastSummary.rejected.map((r, i) => (
                    <li key={i}>
                      <span className="font-mono">{r.filename}</span> — {r.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-ink">Grade</h2>
            <p className="mt-1 text-sm text-ink-muted">
              {isInstructor
                ? "Run OCR + LLM grading on every uploaded PDF. Results appear below for everyone."
                : "Only the instructor can trigger grading. Results will appear below."}
            </p>
          </div>
          <div className="flex gap-2">
            {grades && (
              <button
                type="button"
                onClick={() => navigate(`/exams/${examId}/review`)}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50"
              >
                Open review queue
              </button>
            )}
            {isInstructor && (
              <button
                type="button"
                disabled={grading || !pdfs || pdfs.length === 0}
                onClick={doGrade}
                className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {grading ? "Grading…" : grades ? "Re-grade" : "Grade now"}
              </button>
            )}
          </div>
        </div>

        {grading && (
          <p className="mt-3 text-xs text-ink-muted">
            This may take a few minutes — running OCR on every PDF and a verification pass per
            grade.
          </p>
        )}
        {gradeError && (
          <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {gradeError}
          </div>
        )}
      </section>

      {plagiarism.length > 0 && (
        <section className="mt-6">
          <h2 className="text-base font-semibold text-ink">Suspicious similarity</h2>
          <p className="mt-1 text-xs text-ink-muted">
            Pairs flagged on the latest grading run with cosine similarity ≥ 0.65.
          </p>
          <div className="mt-3 overflow-hidden rounded-lg border border-amber-200 bg-amber-50/40 shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-amber-50 text-left text-xs uppercase tracking-wide text-amber-900">
                <tr>
                  <th className="px-4 py-2 font-medium">Question</th>
                  <th className="px-4 py-2 font-medium">Student A</th>
                  <th className="px-4 py-2 font-medium">Student B</th>
                  <th className="px-4 py-2 font-medium">Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {plagiarism.map((p) => (
                  <tr key={p.id}>
                    <td className="px-4 py-2 font-mono text-xs">{p.question_id}</td>
                    <td className="px-4 py-2 font-mono text-xs">{p.student_a}</td>
                    <td className="px-4 py-2 font-mono text-xs">{p.student_b}</td>
                    <td className="px-4 py-2 font-mono text-xs font-semibold text-amber-900">
                      {p.score.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {grades && <GradesSection summary={grades} examIdentifier={exam?.exam_id ?? "export"} />}

      <section className="mt-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">Uploaded PDFs</h2>
          {pdfs && pdfs.length > 0 && (
            <button
              type="button"
              onClick={doClear}
              disabled={clearing}
              className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 shadow-sm transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {clearing ? "Clearing…" : `Clear all (${pdfs.length})`}
            </button>
          )}
        </div>
        {clearError && (
          <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {clearError}
          </div>
        )}
        {pdfs === null ? (
          <p className="mt-2 text-sm text-ink-muted">Loading…</p>
        ) : pdfs.length === 0 ? (
          <p className="mt-2 text-sm text-ink-muted">None yet.</p>
        ) : (
          <div className="mt-3 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">Filename</th>
                  <th className="px-4 py-3 font-medium">Student</th>
                  <th className="px-4 py-3 font-medium">Question</th>
                  <th className="px-4 py-3 font-medium">Size</th>
                  <th className="px-4 py-3 font-medium">Uploaded</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {pdfs.map((p) => (
                  <tr key={p.id}>
                    <td className="px-4 py-3 font-mono text-xs">{p.filename}</td>
                    <td className="px-4 py-3">{p.student_id ?? "—"}</td>
                    <td className="px-4 py-3">{p.question_id ?? "—"}</td>
                    <td className="px-4 py-3 text-ink-muted">{formatBytes(p.size_bytes)}</td>
                    <td className="px-4 py-3 text-ink-muted">
                      {new Date(p.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {isInstructor && exam && (
        <section className="mt-10 rounded-lg border border-red-200 bg-red-50/40 p-6">
          <h2 className="text-base font-semibold text-red-900">Manage exam</h2>
          <p className="mt-1 text-sm text-red-800/80">
            These actions are permanent. Use them when starting fresh or
            removing an exam entirely.
          </p>
          {manageError && (
            <div className="mt-3 rounded-md border border-red-300 bg-red-100 px-3 py-2 text-sm text-red-800">
              {manageError}
            </div>
          )}
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={doResetGrades}
              disabled={manageBusy !== null || !grades}
              className="rounded-md border border-amber-400 bg-white px-3 py-2 text-sm font-medium text-amber-800 shadow-sm transition hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {manageBusy === "resetGrades"
                ? "Resetting…"
                : "Reset grading results"}
            </button>
            <button
              type="button"
              onClick={doDeleteExam}
              disabled={manageBusy !== null}
              className="rounded-md border border-red-400 bg-white px-3 py-2 text-sm font-medium text-red-800 shadow-sm transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {manageBusy === "deleteExam" ? "Deleting…" : "Delete this exam"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
