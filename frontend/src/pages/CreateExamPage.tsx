import { useState, type ChangeEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { createExam } from "@/api/client";

export function CreateExamPage() {
  const navigate = useNavigate();
  const [filename, setFilename] = useState<string | null>(null);
  const [rubric, setRubric] = useState<Record<string, unknown> | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    setParseError(null);
    setServerError(null);
    setRubric(null);
    setFilename(null);

    const file = e.target.files?.[0];
    if (!file) return;
    setFilename(file.name);

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          setParseError("Rubric JSON must be an object at the top level.");
          return;
        }
        const missing = ["exam_id", "course"].filter((k) => !parsed[k]);
        if (missing.length > 0) {
          setParseError(`Missing required fields: ${missing.join(", ")}`);
          return;
        }
        if (typeof parsed.total_marks !== "number") {
          setParseError("Rubric must have a numeric `total_marks` field.");
          return;
        }
        if (!Array.isArray(parsed.questions) || parsed.questions.length === 0) {
          setParseError("Rubric must have at least one entry in `questions`.");
          return;
        }
        setRubric(parsed as Record<string, unknown>);
      } catch (err) {
        setParseError(`Invalid JSON: ${(err as Error).message}`);
      }
    };
    reader.readAsText(file);
  }

  async function onSubmit() {
    if (!rubric) return;
    setSubmitting(true);
    setServerError(null);
    try {
      const exam = await createExam(rubric);
      navigate(`/exams/${exam.id}`, { replace: true });
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setServerError(ax.response?.data?.detail ?? ax.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <Link to="/exams" className="text-xs font-medium text-accent hover:underline">
        ← Back to exams
      </Link>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">New exam</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Upload a rubric JSON. It must include <code>exam_id</code> and <code>course</code>
        {" "}(<code>title</code> is optional — defaults to <code>exam_id</code>).
      </p>

      <div className="mt-6 space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div>
          <label className="block text-sm font-medium text-ink-soft" htmlFor="rubric-file">
            Rubric JSON
          </label>
          <input
            id="rubric-file"
            type="file"
            accept="application/json,.json"
            onChange={onFile}
            className="mt-2 block w-full text-sm text-ink-soft file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink-soft hover:file:bg-slate-200"
          />
          {filename && (
            <p className="mt-1 text-xs text-ink-muted">Selected: {filename}</p>
          )}
        </div>

        {parseError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {parseError}
          </div>
        )}

        {rubric && !parseError && (
          <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            Parsed: <span className="font-mono">{String(rubric.exam_id)}</span> ·{" "}
            {String(rubric.course)}
            {rubric.title ? ` · ${String(rubric.title)}` : ""}
          </div>
        )}

        {serverError && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {serverError}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Link
            to="/exams"
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50"
          >
            Cancel
          </Link>
          <button
            type="button"
            disabled={!rubric || submitting}
            onClick={onSubmit}
            className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Creating…" : "Create exam"}
          </button>
        </div>
      </div>
    </div>
  );
}
