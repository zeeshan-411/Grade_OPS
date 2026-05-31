import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthContext";
import { PrivateRoute } from "@/auth/PrivateRoute";
import { LoginPage } from "@/pages/LoginPage";
import { HomePage } from "@/pages/HomePage";
import { ExamsPage } from "@/pages/ExamsPage";
import { CreateExamPage } from "@/pages/CreateExamPage";
import { ExamDetailPage } from "@/pages/ExamDetailPage";
import { ReviewPage } from "@/pages/ReviewPage";

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <PrivateRoute>
                <HomePage />
              </PrivateRoute>
            }
          />
          <Route
            path="/exams"
            element={
              <PrivateRoute>
                <ExamsPage />
              </PrivateRoute>
            }
          />
          <Route
            path="/exams/new"
            element={
              <PrivateRoute requireRole="INSTRUCTOR">
                <CreateExamPage />
              </PrivateRoute>
            }
          />
          <Route
            path="/exams/:examId"
            element={
              <PrivateRoute>
                <ExamDetailPage />
              </PrivateRoute>
            }
          />
          <Route
            path="/exams/:examId/review"
            element={
              <PrivateRoute>
                <ReviewPage />
              </PrivateRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
