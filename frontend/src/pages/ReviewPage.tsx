import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AxiosError } from "axios";
import {
  fetchPdfBlobUrl,
  getReviewQueue,
  submitReview,
  type ReviewAction,
  type ReviewQueueItem,
} from "@/api/client";
import { useAuth } from "@/auth/AuthContext";

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

function ActionBadge({ action }: { action: ReviewAction }) {
  const map: Record<ReviewAction, string> = {
    APPROVE: "bg-emerald-100 text-emerald-800 ring-emerald-200",
    OVERRIDE: "bg-blue-100 text-blue-800 ring-blue-200",
    FLAG: "bg-amber-100 text-amber-800 ring-amber-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${map[action]}`}
    >
      {action}
    </span>
  );
}

export function ReviewPage() {
  const { examId } = useParams<{ examId: string }>();
  const { user } = useAuth();
  const isTA = user?.role === "TA";

  const [items, setItems] = useState<ReviewQueueItem[] | null>(null);
  const [index, setIndex] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const pdfBlobsRef = useRef<Map<string, string>>(new Map());
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideScore, setOverrideScore] = useState<string>("");
  const overrideInputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    if (!examId) return;
    try {
      const q = await getReviewQueue(examId);
      setItems(q);
    } catch (err) {
      const ax = err as AxiosError<{ detail?: string }>;
      setLoadError(ax.response?.data?.detail ?? ax.message);
    }
  }, [examId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const current = items && items.length > 0 ? items[index] : null;

  // Fetch (and cache) the PDF blob URL once per pdf_id; navigating between
  // questions on the same student just appends a #page=N fragment so the
  // browser's PDF viewer scrolls without re-fetching.
  useEffect(() => {
    if (!current?.pdf_id || !examId) {
      setPdfUrl(null);
      return;
    }
    const cached = pdfBlobsRef.current.get(current.pdf_id);
    const page = current.pdf_page ?? 1;
    const fragment = `#page=${page}&zoom=page-fit`;
    if (cached) {
      setPdfUrl(cached + fragment);
      return;
    }
    let cancelled = false;
    fetchPdfBlobUrl(examId, current.pdf_id)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        pdfBlobsRef.current.set(current.pdf_id!, url);
        setPdfUrl(url + fragment);
      })
      .catch(() => {
        if (!cancelled) setPdfUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [current, examId]);

  // Release all cached blob URLs when leaving the page.
  useEffect(() => {
    const cache = pdfBlobsRef.current;
    return () => {
      for (const url of cache.values()) URL.revokeObjectURL(url);
      cache.clear();
    };
  }, []);

  const total = items?.length ?? 0;
  const reviewedCount = useMemo(
    () => (items ? items.filter((i) => i.review).length : 0),
    [items],
  );

  const goPrev = useCallback(() => {
    setOverrideOpen(false);
    setSubmitError(null);
    setIndex((i) => Math.max(0, i - 1));
  }, []);
  const goNext = useCallback(() => {
    setOverrideOpen(false);
    setSubmitError(null);
    setIndex((i) => (items ? Math.min(items.length - 1, i + 1) : 0));
  }, [items]);

  const doSubmit = useCallback(
    async (action: ReviewAction, scoreOverride?: number) => {
      if (!current || !isTA) return;
      setSubmitting(true);
      setSubmitError(null);
      try {
        const updated = await submitReview(current.grade_id, {
          question_id: current.question_id,
          action,
          override_score: action === "OVERRIDE" ? (scoreOverride ?? null) : null,
        });
        setItems((prev) =>
          prev
            ? prev.map((it, i) => (i === index ? { ...it, review: updated } : it))
            : prev,
        );
        setOverrideOpen(false);
        // auto-advance to next unreviewed
        const nextIdx =
          items?.findIndex((it, i) => i > index && !it.review) ?? -1;
        if (nextIdx >= 0) setIndex(nextIdx);
        else if (items && index < items.length - 1) setIndex(index + 1);
      } catch (err) {
        const ax = err as AxiosError<{ detail?: string }>;
        setSubmitError(ax.response?.data?.detail ?? ax.message);
      } finally {
        setSubmitting(false);
      }
    },
    [current, isTA, index, items],
  );

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        if (e.key === "Enter" && overrideOpen) {
          e.preventDefault();
          const n = parseFloat(overrideScore);
          if (!Number.isNaN(n)) doSubmit("OVERRIDE", n);
        }
        return;
      }
      if (e.key === "ArrowRight" || e.key.toLowerCase() === "j") {
        e.preventDefault();
        goNext();
      } else if (e.key === "ArrowLeft" || e.key.toLowerCase() === "k") {
        e.preventDefault();
        goPrev();
      } else if (e.key.toLowerCase() === "a" && isTA) {
        e.preventDefault();
        doSubmit("APPROVE");
      } else if (e.key.toLowerCase() === "o" && isTA) {
        e.preventDefault();
        setOverrideOpen(true);
        setOverrideScore(String(current?.ai_score ?? ""));
        setTimeout(() => overrideInputRef.current?.focus(), 0);
      } else if (e.key.toLowerCase() === "f" && isTA) {
        e.preventDefault();
        doSubmit("FLAG");
      } else if (e.key === "Escape") {
        setOverrideOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext, goPrev, doSubmit, isTA, current, overrideOpen, overrideScore]);

  if (loadError) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <Link to={`/exams/${examId}`} className="text-xs font-medium text-accent hover:underline">
          ← Back to exam
        </Link>
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {loadError}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <header className="flex items-center justify-between border-b border-slate-200 pb-4">
        <div>
          <Link to={`/exams/${examId}`} className="text-xs font-medium text-accent hover:underline">
            ← Back to exam
          </Link>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-ink">Review queue</h1>
          {items && (
            <p className="text-xs text-ink-muted">
              {reviewedCount} / {total} reviewed
              {!isTA && (
                <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-ink-soft">
                  read-only — TA role required to submit
                </span>
              )}
            </p>
          )}
        </div>
        <div className="hidden text-xs text-ink-muted sm:block">
          <kbd className="rounded border px-1.5 py-0.5">A</kbd> approve ·{" "}
          <kbd className="rounded border px-1.5 py-0.5">O</kbd> override ·{" "}
          <kbd className="rounded border px-1.5 py-0.5">F</kbd> flag ·{" "}
          <kbd className="rounded border px-1.5 py-0.5">←</kbd>/<kbd className="rounded border px-1.5 py-0.5">→</kbd> prev/next
        </div>
      </header>

      {items === null && <p className="mt-6 text-sm text-ink-muted">Loading…</p>}
      {items && items.length === 0 && (
        <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center">
          <p className="text-sm text-ink-muted">
            No graded answers yet — ask the instructor to grade this exam first.
          </p>
        </div>
      )}

      {current && (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Left: PDF */}
          <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
              <p className="text-sm font-medium text-ink-soft">
                {current.pdf_filename ?? "No source PDF"}
              </p>
              <p className="text-xs text-ink-muted">
                {index + 1} / {total}
              </p>
            </div>
            <div className="h-[calc(100vh-220px)] bg-slate-50">
              {pdfUrl ? (
                <iframe
                  src={pdfUrl}
                  title="student answer"
                  className="h-full w-full"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-ink-muted">
                  {current.pdf_id ? "Loading PDF…" : "No PDF on file for this answer."}
                </div>
              )}
            </div>
          </div>

          {/* Right: AI grade + actions */}
          <div className="flex flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 px-4 py-3">
              <div className="flex items-center justify-between">
                <p className="font-mono text-sm font-semibold text-ink">
                  {current.student_id} · {current.question_id}
                </p>
                <div className="flex items-center gap-1.5">
                  {current.ai_verified && (
                    <span className="text-xs font-medium text-emerald-700">verified</span>
                  )}
                  {current.ai_flags.map((f) => (
                    <FlagBadge key={f} flag={f} />
                  ))}
                </div>
              </div>
              <p className="mt-1 text-2xl font-semibold text-ink">
                {current.ai_score.toFixed(0)}{" "}
                <span className="text-sm font-normal text-ink-muted">
                  / {current.max_marks.toFixed(0)} AI score
                </span>
              </p>

              {current.plagiarism_partners.length > 0 && (
                <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  <p className="font-semibold">Similarity flag</p>
                  <p className="mt-0.5">
                    This answer matches{" "}
                    {current.plagiarism_partners.map((p, i) => (
                      <span key={p.student_id}>
                        {i > 0 && ", "}
                        <span className="font-mono">{p.student_id}</span>{" "}
                        ({p.score.toFixed(2)})
                      </span>
                    ))}
                    .
                  </p>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-auto px-4 py-3">
              {current.ai_summary && (
                <p className="mb-3 text-sm italic text-ink-soft">{current.ai_summary}</p>
              )}
              <ul className="space-y-2 text-sm">
                {current.ai_criteria.map((c) => (
                  <li key={c.criterion_id} className="rounded-md border border-slate-100 p-2">
                    <div className="flex items-baseline justify-between">
                      <span className="font-mono text-xs text-ink-muted">{c.criterion_id}</span>
                      <span className="font-mono text-xs text-ink-soft">
                        {c.marks_awarded.toFixed(0)}
                      </span>
                    </div>
                    <p className="text-ink-soft">{c.justification}</p>
                  </li>
                ))}
              </ul>
            </div>

            <div className="border-t border-slate-200 px-4 py-3">
              {current.review && (
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-ink-muted">
                    Last reviewed by {current.review.reviewed_by_email} —{" "}
                    {new Date(current.review.created_at).toLocaleString()}
                  </span>
                  <div className="flex items-center gap-2">
                    <ActionBadge action={current.review.action} />
                    {current.review.action === "OVERRIDE" && (
                      <span className="font-mono text-xs text-blue-700">
                        → {current.review.override_score?.toFixed(0)}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {submitError && (
                <div className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {submitError}
                </div>
              )}

              {overrideOpen && (
                <div className="mb-2 flex items-center gap-2">
                  <input
                    ref={overrideInputRef}
                    type="number"
                    inputMode="decimal"
                    min={0}
                    max={current.max_marks}
                    value={overrideScore}
                    onChange={(e) => setOverrideScore(e.target.value)}
                    className="w-24 rounded-md border border-slate-300 px-2 py-1 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                    placeholder="New score"
                  />
                  <span className="text-xs text-ink-muted">
                    / {current.max_marks.toFixed(0)} — Enter to confirm, Esc to cancel
                  </span>
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={!isTA || submitting}
                  onClick={() => doSubmit("APPROVE")}
                  className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Approve <kbd className="ml-1 rounded bg-white/20 px-1 text-xs">A</kbd>
                </button>
                <button
                  type="button"
                  disabled={!isTA || submitting}
                  onClick={() => {
                    setOverrideOpen(true);
                    setOverrideScore(String(current.ai_score));
                    setTimeout(() => overrideInputRef.current?.focus(), 0);
                  }}
                  className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Override <kbd className="ml-1 rounded bg-white/20 px-1 text-xs">O</kbd>
                </button>
                <button
                  type="button"
                  disabled={!isTA || submitting}
                  onClick={() => doSubmit("FLAG")}
                  className="rounded-md bg-amber-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Flag <kbd className="ml-1 rounded bg-white/20 px-1 text-xs">F</kbd>
                </button>

                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    onClick={goPrev}
                    disabled={index === 0}
                    className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    ← Prev
                  </button>
                  <button
                    type="button"
                    onClick={goNext}
                    disabled={total === 0 || index >= total - 1}
                    className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Next →
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
