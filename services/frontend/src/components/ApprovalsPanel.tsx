import { useCallback, useEffect, useState } from "react";
import { decideApproval, listPendingApprovals, type Approval } from "../api/approvals";
import { ApiError } from "../api/client";

interface Props {
  token: string;
  onUnauthorized: () => void;
}

export default function ApprovalsPanel({ token, onUnauthorized }: Props) {
  const [items, setItems] = useState<Approval[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFailure = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      else setError("Something went wrong. Try again.");
    },
    [onUnauthorized],
  );

  const refresh = useCallback(() => {
    listPendingApprovals(token)
      .then((list) => setItems(list.data))
      .catch(handleFailure);
  }, [token, handleFailure]);

  useEffect(refresh, [refresh]);

  async function decide(id: string, decision: "approved" | "denied") {
    setError(null);
    try {
      await decideApproval(token, id, decision);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 409)) {
        handleFailure(err);
        return;
      }
    }
    refresh();
  }

  return (
    <section
      aria-labelledby="approvals-heading"
      className="rounded-lg border border-line bg-panel p-5"
    >
      <h2 id="approvals-heading" className="text-sm font-medium text-muted">
        Pending approvals
      </h2>
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
      {items === null ? (
        <p className="mt-3 text-sm text-muted">Loading...</p>
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No pending approvals.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {items.map((item) => (
            <li key={item.id} className="py-2">
              <p className="text-sm font-medium">{item.action}</p>
              {item.description && <p className="text-sm text-muted">{item.description}</p>}
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  aria-label={`Approve ${item.action}`}
                  onClick={() => decide(item.id, "approved")}
                  className="rounded bg-accent px-3 py-1 text-sm font-medium text-surface"
                >
                  Approve
                </button>
                <button
                  type="button"
                  aria-label={`Deny ${item.action}`}
                  onClick={() => decide(item.id, "denied")}
                  className="rounded border border-line px-3 py-1 text-sm text-muted hover:text-danger"
                >
                  Deny
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
