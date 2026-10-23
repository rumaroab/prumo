import { useEffect, useRef, type ComponentPropsWithoutRef } from "react";
import { createPortal } from "react-dom";
import "../../design-tokens.css";

export type DialogProps = Omit<
  ComponentPropsWithoutRef<"dialog">,
  "open" | "onCancel"
> & {
  onDismiss?: () => void;
};

/** Native modal focus containment and inert background; keeps the caller's close action. */
export function Dialog({
  onDismiss,
  onKeyDown,
  className,
  children,
  ...props
}: DialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const element = dialog.current;
    element?.showModal();
    return () => {
      element?.close();
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <dialog
      {...props}
      ref={dialog}
      tabIndex={-1}
      className={["ds-dialog", className].filter(Boolean).join(" ")}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented || event.key !== "Tab") return;
        const controls = Array.from(
          event.currentTarget.querySelectorAll<HTMLElement>(
            "a[href], button, input, select, textarea, summary, [tabindex]",
          ),
        ).filter(
          (element) =>
            element.tabIndex >= 0 &&
            !element.matches(":disabled") &&
            element.getClientRects().length > 0,
        );
        const first = controls[0];
        const last = controls.at(-1);
        if (!first) {
          event.preventDefault();
          event.currentTarget.focus();
        } else if (
          event.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === event.currentTarget)
        ) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        onDismiss?.();
      }}
    >
      {children}
    </dialog>,
    document.body,
  );
}
