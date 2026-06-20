// Lightweight confirmation modal (dark theme). Backdrop click / Cancel dismiss.
export default function ConfirmModal({
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  busyLabel = "Working…",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}) {
  return (
    <div className="mb-modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div className="mb-modal card" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p className="muted">{message}</p>
        <div className="mb-modal-actions">
          <button className="mb-btn-ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            className={danger ? "btn-stop" : ""}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? busyLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
