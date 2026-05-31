import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { deleteExam, listExams, type ExamSummary } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { AxiosError } from "axios";

export function ExamsPage() {
  const { user, signOut } = useAuth();
  const [exams, setExams] = useState<ExamSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    listExams()
      .then(setExams)
      .catch((e: AxiosError<{ detail?: string }>) => {
        setError(e.response?.data?.detail ?? e.message);
      });
  }, []);

  async function onDelete(exam: ExamSummary) {
    if (
      !confirm(
        `Delete exam "${exam.exam_id}"?\n\nThis will also remove its PDFs, grading runs, reviews, and plagiarism flags. This cannot be undone.`,
      )
    )
      return;
    setDeletingId(exam.id);
    setError(null);
    try {
      await deleteExam(exam.id);
      setExams((prev) => (prev ? prev.filter((e) => e.id !== exam.id) : prev));
    } catch (e) {
      const ax = e as AxiosError<{ detail?: string }>;
      setError(ax.response?.data?.detail ?? ax.message);
    } finally {
      setDeletingId(null);
    }
  }

  if (!user) return null;
  const isInstructor = user.role === "INSTRUCTOR";

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <header className="flex items-start justify-between border-b border-slate-200 pb-6">
        <div>
          <Link to="/" className="text-xs font-medium text-accent hover:underline">
            ← Home
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">Exams</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {isInstructor
              ? "Create a new exam from a rubric, then upload student PDFs."
              : "Pick an exam and upload student answer PDFs."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isInstructor && (
            <Link
              to="/exams/new"
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-accent-hover"
            >
              New exam
            </Link>
          )}
          <button
            onClick={signOut}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="mt-8">
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {exams === null && !error && (
          <p className="text-sm text-ink-muted">Loading…</p>
        )}

        {exams && exams.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
            <p className="text-sm text-ink-muted">No exams yet.</p>
            {isInstructor && (
              <p className="mt-1 text-xs text-ink-muted">
                Click <span className="font-medium">New exam</span> to upload a rubric.
              </p>
            )}
          </div>
        )}

        {exams && exams.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">Exam ID</th>
                  <th className="px-4 py-3 font-medium">Course</th>
                  <th className="px-4 py-3 font-medium">Title</th>
                  <th className="px-4 py-3 font-medium">PDFs</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                  {isInstructor && <th className="px-4 py-3 font-medium text-right">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {exams.map((e) => (
                  <tr key={e.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-xs text-ink-soft">
                      <Link to={`/exams/${e.id}`} className="text-accent hover:underline">
                        {e.exam_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{e.course}</td>
                    <td className="px-4 py-3">{e.title}</td>
                    <td className="px-4 py-3 text-ink-muted">{e.pdf_count}</td>
                    <td className="px-4 py-3 text-ink-muted">
                      {new Date(e.created_at).toLocaleString()}
                    </td>
                    {isInstructor && (
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          disabled={deletingId === e.id}
                          onClick={() => onDelete(e)}
                          className="rounded-md border border-red-300 bg-white px-2 py-1 text-xs font-medium text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {deletingId === e.id ? "Deleting…" : "Delete"}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
