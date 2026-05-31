import { Link } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";

export function HomePage() {
  const { user, signOut } = useAuth();
  if (!user) return null;

  const isInstructor = user.role === "INSTRUCTOR";

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <header className="flex items-start justify-between border-b border-slate-200 pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">GradeOps</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Signed in as <span className="font-medium text-ink-soft">{user.email}</span>
            <span className="ml-2 inline-block rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-ink-soft">
              {user.role}
            </span>
          </p>
        </div>
        <button
          onClick={signOut}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-ink-soft shadow-sm transition hover:bg-slate-50"
        >
          Sign out
        </button>
      </header>

      <main className="mt-8 grid gap-4 sm:grid-cols-2">
        <ActionCard
          to="/exams"
          title="Exams"
          body={
            isInstructor
              ? "Create exams from rubrics and upload student PDFs."
              : "Browse exams and upload student answer PDFs."
          }
          cta={isInstructor ? "Open" : "Open"}
        />
        <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold text-ink">Account</h2>
          <p className="mt-1 text-sm leading-relaxed text-ink-muted">
            Role: {user.role}. Active since{" "}
            {new Date(user.created_at).toLocaleDateString()}.
          </p>
        </div>
      </main>
    </div>
  );
}

function ActionCard({
  to,
  title,
  body,
  cta,
}: {
  to: string;
  title: string;
  body: string;
  cta: string;
}) {
  return (
    <Link
      to={to}
      className="block rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition hover:border-accent hover:shadow-md"
    >
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <p className="mt-1 text-sm leading-relaxed text-ink-muted">{body}</p>
      <p className="mt-3 text-xs font-medium uppercase tracking-wide text-accent">{cta}</p>
    </Link>
  );
}
