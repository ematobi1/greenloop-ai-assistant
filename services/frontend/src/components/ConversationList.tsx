import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import {
  createConversation,
  deleteConversation,
  listConversations,
  type Conversation,
} from "../api/conversations";

interface Props {
  token: string;
  onUnauthorized: () => void;
}

export default function ConversationList({ token, onUnauthorized }: Props) {
  const [items, setItems] = useState<Conversation[] | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleFailure = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else setError("Something went wrong. Try again.");
    },
    [onUnauthorized],
  );

  const refresh = useCallback(() => {
    listConversations(token)
      .then((list) => setItems(list.data))
      .catch(handleFailure);
  }, [token, handleFailure]);

  useEffect(refresh, [refresh]);

  async function add(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setError(null);
    try {
      await createConversation(token, title);
      setTitle("");
      refresh();
    } catch (err) {
      handleFailure(err);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await deleteConversation(token, id);
      refresh();
    } catch (err) {
      handleFailure(err);
    }
  }

  return (
    <section
      aria-labelledby="conversations-heading"
      className="rounded-lg border border-line bg-panel p-5 sm:col-span-2"
    >
      <h2 id="conversations-heading" className="text-sm font-medium text-muted">
        Conversations
      </h2>
      <form onSubmit={add} className="mt-3 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="conversation-title" className="text-sm text-muted">
            New conversation title
          </label>
          <input
            id="conversation-title"
            type="text"
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className="w-64 rounded border border-line bg-surface px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-surface"
        >
          Create
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
      {items === null ? (
        <p className="mt-3 text-sm text-muted">Loading...</p>
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No conversations yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 py-2">
              <span className="truncate text-sm">{item.title}</span>
              <button
                type="button"
                aria-label={`Delete ${item.title}`}
                onClick={() => remove(item.id)}
                className="rounded border border-line px-3 py-1 text-sm text-muted hover:text-danger"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
