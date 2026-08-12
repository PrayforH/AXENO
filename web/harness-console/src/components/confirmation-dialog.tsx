"use client";

import { createPortal } from "react-dom";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import styles from "./confirmation-dialog.module.css";

export type ConfirmationRequest = {
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  context?: ReactNode;
  tone?: "default" | "danger";
};

export type ConfirmationRequester = (
  request: ConfirmationRequest,
) => Promise<boolean>;

type ConfirmationDialogProps = {
  request: ConfirmationRequest | null;
  onResolve: (confirmed: boolean) => void;
};

function ConfirmationDialog({ request, onResolve }: ConfirmationDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!request) return;
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const focusTimer = window.setTimeout(() => cancelRef.current?.focus(), 20);
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onResolve(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (!panelRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", onKeyDown);
      window.requestAnimationFrame(() => previousFocusRef.current?.focus());
    };
  }, [onResolve, request]);

  if (!request) return null;

  return createPortal(
    <div
      className={styles.backdrop}
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onResolve(false);
      }}
    >
      <div
        ref={panelRef}
        className={styles.dialog}
        data-tone={request.tone ?? "default"}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <div className={styles.signal} aria-hidden="true">
          <span>{request.tone === "danger" ? "!" : "i"}</span>
        </div>
        <div className={styles.copy}>
          <span className={styles.eyebrow}>
            {request.tone === "danger" ? "IRREVERSIBLE ACTION" : "CONFIRM CHANGE"}
          </span>
          <h2 id={titleId}>{request.title}</h2>
          <p id={descriptionId}>{request.description}</p>
          {request.context && <div className={styles.context}>{request.context}</div>}
        </div>
        <div className={styles.actions}>
          <button
            ref={cancelRef}
            type="button"
            className={styles.cancel}
            onClick={() => onResolve(false)}
          >
            {request.cancelLabel ?? "取消"}
          </button>
          <button
            type="button"
            className={styles.confirm}
            onClick={() => onResolve(true)}
          >
            {request.confirmLabel ?? "确认"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function useConfirmationDialog(): {
  requestConfirmation: ConfirmationRequester;
  confirmationDialog: ReactNode;
} {
  const [request, setRequest] = useState<ConfirmationRequest | null>(null);
  const resolverRef = useRef<((confirmed: boolean) => void) | null>(null);

  const resolve = useCallback((confirmed: boolean) => {
    const resolver = resolverRef.current;
    resolverRef.current = null;
    setRequest(null);
    resolver?.(confirmed);
  }, []);

  const requestConfirmation = useCallback<ConfirmationRequester>(
    (nextRequest) =>
      new Promise<boolean>((resolver) => {
        resolverRef.current?.(false);
        resolverRef.current = resolver;
        setRequest(nextRequest);
      }),
    [],
  );

  useEffect(
    () => () => {
      resolverRef.current?.(false);
      resolverRef.current = null;
    },
    [],
  );

  return {
    requestConfirmation,
    confirmationDialog: (
      <ConfirmationDialog request={request} onResolve={resolve} />
    ),
  };
}
