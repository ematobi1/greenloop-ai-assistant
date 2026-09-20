import { request } from "./client";

export interface Approval {
  id: string;
  action: string;
  description: string;
  status: "pending" | "approved" | "denied";
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

interface List<T> {
  data: T[];
  meta: { total: number };
}

export const listPendingApprovals = (token: string) =>
  request<List<Approval>>("/v1/approvals?status=pending&limit=100", token);

export const decideApproval = (token: string, id: string, decision: "approved" | "denied") =>
  request<Approval>(`/v1/approvals/${encodeURIComponent(id)}/decision`, token, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
