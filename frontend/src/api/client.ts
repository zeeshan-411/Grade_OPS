import axios from "axios";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

const TOKEN_KEY = "gradeops_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      setToken(null);
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

export type Role = "INSTRUCTOR" | "TA";

export interface User {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export async function login(email: string, password: string): Promise<string> {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  const { data } = await api.post<{ access_token: string }>(
    "/api/v1/auth/login",
    form,
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } },
  );
  setToken(data.access_token);
  return data.access_token;
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>("/api/v1/users/me");
  return data;
}

// ──────────────────────────────────────────────────────────────────────
// Exams
// ──────────────────────────────────────────────────────────────────────

export interface ExamSummary {
  id: string;
  exam_id: string;
  course: string;
  title: string;
  owner_id: string;
  created_at: string;
  pdf_count: number;
}

export interface ExamDetail extends ExamSummary {
  rubric_json: Record<string, unknown>;
}

export interface ExamPdf {
  id: string;
  filename: string;
  student_id: string | null;
  question_id: string | null;
  size_bytes: number;
  uploaded_by_id: string;
  created_at: string;
}

export interface UploadSummary {
  uploaded: ExamPdf[];
  rejected: Array<{ filename: string; reason: string }>;
}

export async function listExams(): Promise<ExamSummary[]> {
  const { data } = await api.get<ExamSummary[]>("/api/v1/exams");
  return data;
}

export async function getExam(id: string): Promise<ExamDetail> {
  const { data } = await api.get<ExamDetail>(`/api/v1/exams/${id}`);
  return data;
}

export async function createExam(rubric: Record<string, unknown>): Promise<ExamSummary> {
  const { data } = await api.post<ExamSummary>("/api/v1/exams", { rubric });
  return data;
}

export async function listExamPdfs(examId: string): Promise<ExamPdf[]> {
  const { data } = await api.get<ExamPdf[]>(`/api/v1/exams/${examId}/pdfs`);
  return data;
}

export async function clearExamPdfs(examId: string): Promise<{ deleted: number }> {
  const { data } = await api.delete<{ deleted: number }>(
    `/api/v1/exams/${examId}/pdfs`,
  );
  return data;
}

export async function clearExamGrades(examId: string): Promise<{ deleted_runs: number }> {
  const { data } = await api.delete<{ deleted_runs: number }>(
    `/api/v1/exams/${examId}/grades`,
  );
  return data;
}

export async function deleteExam(examId: string): Promise<{ deleted: string }> {
  const { data } = await api.delete<{ deleted: string }>(`/api/v1/exams/${examId}`);
  return data;
}

export async function uploadExamPdfs(examId: string, files: File[]): Promise<UploadSummary> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const { data } = await api.post<UploadSummary>(
    `/api/v1/exams/${examId}/pdfs`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

// ──────────────────────────────────────────────────────────────────────
// Grading
// ──────────────────────────────────────────────────────────────────────

export type RunStatus = "PENDING" | "RUNNING" | "DONE" | "FAILED";

export interface GradingRun {
  id: string;
  exam_fk: string;
  started_by_id: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  error_msg: string | null;
  n_students: number | null;
  n_pdfs: number | null;
}

export interface CriterionResult {
  criterion_id: string;
  marks_awarded: number;
  justification: string;
}

export interface DeductionResult {
  condition: string;
  penalty: number;
  applied: boolean;
}

export interface QuestionGrade {
  question_id: string;
  total_marks: number;
  max_marks: number;
  verified: boolean;
  flags: string[];
  summary: string;
  criterion_results: CriterionResult[];
  deduction_results: DeductionResult[];
}

export interface StudentGradePayload {
  student_id: string;
  total_score: number;
  max_possible: number;
  flags: string[];
  question_grades: QuestionGrade[];
}

export interface StudentGradeRow {
  id: string;
  run_fk: string;
  student_id: string;
  total_score: number;
  max_possible: number;
  needs_review: boolean;
  verified: boolean;
  flags: string[];
  payload: StudentGradePayload;
  created_at: string;
}

export interface GradeSummary {
  run: GradingRun;
  grades: StudentGradeRow[];
  total_students: number;
  total_score: number;
  max_possible: number;
  needs_review: number;
  verified: number;
}

export async function getExamGrades(examId: string): Promise<GradeSummary | null> {
  const { data } = await api.get<GradeSummary | null>(`/api/v1/exams/${examId}/grades`);
  return data;
}

export async function triggerGrading(examId: string): Promise<GradeSummary> {
  const { data } = await api.post<GradeSummary>(
    `/api/v1/exams/${examId}/grade`,
    null,
    { timeout: 10 * 60 * 1000 }, // 10 minutes — grading can be slow
  );
  return data;
}

// ──────────────────────────────────────────────────────────────────────
// TA review
// ──────────────────────────────────────────────────────────────────────

export type ReviewAction = "APPROVE" | "OVERRIDE" | "FLAG";

export interface Review {
  id: string;
  student_grade_id: string;
  question_id: string;
  reviewed_by_id: string;
  reviewed_by_email: string;
  action: ReviewAction;
  override_score: number | null;
  comment: string | null;
  created_at: string;
}

export interface PlagiarismPartner {
  student_id: string;
  score: number;
}

export interface ReviewQueueItem {
  grade_id: string;
  student_id: string;
  question_id: string;
  ai_score: number;
  max_marks: number;
  ai_verified: boolean;
  ai_summary: string;
  ai_flags: string[];
  ai_criteria: CriterionResult[];
  pdf_id: string | null;
  pdf_filename: string | null;
  pdf_page: number | null;
  review: Review | null;
  plagiarism_partners: PlagiarismPartner[];
}

export interface ReviewIn {
  question_id: string;
  action: ReviewAction;
  override_score?: number | null;
  comment?: string | null;
}

export async function getReviewQueue(examId: string): Promise<ReviewQueueItem[]> {
  const { data } = await api.get<ReviewQueueItem[]>(
    `/api/v1/exams/${examId}/review/queue`,
  );
  return data;
}

export async function submitReview(gradeId: string, body: ReviewIn): Promise<Review> {
  const { data } = await api.post<Review>(`/api/v1/grades/${gradeId}/review`, body);
  return data;
}

export function pdfFileUrl(examId: string, pdfId: string): string {
  // Used by <iframe>. Token must be on the URL since iframes can't set headers;
  // we use a short-lived signed query token below if needed. For now the PDF
  // endpoint authenticates via the standard cookie/bearer flow — embed via
  // fetch + object URL in components that need it.
  return `${api.defaults.baseURL}/api/v1/exams/${examId}/pdfs/${pdfId}/file`;
}

export async function fetchPdfBlobUrl(examId: string, pdfId: string): Promise<string> {
  const resp = await api.get(`/api/v1/exams/${examId}/pdfs/${pdfId}/file`, {
    responseType: "blob",
  });
  return URL.createObjectURL(resp.data as Blob);
}

// ──────────────────────────────────────────────────────────────────────
// Plagiarism
// ──────────────────────────────────────────────────────────────────────

export interface PlagiarismPair {
  id: string;
  question_id: string;
  student_a: string;
  student_b: string;
  score: number;
  created_at: string;
}

export async function listPlagiarism(examId: string): Promise<PlagiarismPair[]> {
  const { data } = await api.get<PlagiarismPair[]>(`/api/v1/exams/${examId}/plagiarism`);
  return data;
}
