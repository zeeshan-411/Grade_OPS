import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import type { ReactNode } from "react";
import type { Role } from "@/api/client";

interface Props {
  children: ReactNode;
  requireRole?: Role | Role[];
}

export function PrivateRoute({ children, requireRole }: Props) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-ink-muted">
        Loading…
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  if (requireRole) {
    const allowed = Array.isArray(requireRole) ? requireRole : [requireRole];
    if (!allowed.includes(user.role)) {
      return (
        <div className="flex h-full items-center justify-center">
          <div className="rounded-lg border border-slate-200 bg-white p-6 text-center shadow-sm">
            <h2 className="text-lg font-semibold text-ink">Forbidden</h2>
            <p className="mt-1 text-sm text-ink-muted">
              Your role ({user.role}) cannot access this page.
            </p>
          </div>
        </div>
      );
    }
  }
  return <>{children}</>;
}
