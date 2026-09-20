import { request } from "./client";

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface List<T> {
  data: T[];
  meta: { total: number };
}

export const listConversations = (token: string) =>
  request<List<Conversation>>("/v1/conversations?limit=100", token);

export const createConversation = (token: string, title: string) =>
  request<Conversation>("/v1/conversations", token, {
    method: "POST",
    body: JSON.stringify({ title }),
  });

export const deleteConversation = (token: string, id: string) =>
  request<void>(`/v1/conversations/${encodeURIComponent(id)}`, token, { method: "DELETE" });
