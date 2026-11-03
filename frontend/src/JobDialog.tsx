import { useId, useLayoutEffect, useRef, type ReactNode } from "react";

export function JobDialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useLayoutEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    const scrollX = window.scrollX,
      scrollY = window.scrollY;
    const ancestors: { element: HTMLElement; left: number; top: number }[] = [];
    for (
      let element = opener?.parentElement;
      element;
      element = element.parentElement
    )
      ancestors.push({
        element,
        left: element.scrollLeft,
        top: element.scrollTop,
      });
    const dialog = ref.current;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = overflow;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
      for (const { element, left, top } of ancestors)
        element.scrollTo({ left, top, behavior: "instant" });
      window.scrollTo({ left: scrollX, top: scrollY, behavior: "instant" });
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="jq-dialog"
      aria-labelledby={titleId}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = [
          ...event.currentTarget.querySelectorAll<HTMLElement>(
            'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
          ),
        ].filter((el) => el.tabIndex >= 0 && el.getClientRects().length > 0);
        const first = controls[0],
          last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="jq-dialog-head">
        <h2 id={titleId}>{title}</h2>
        <button onClick={onClose} aria-label="关闭详情">
          关闭
        </button>
      </header>
      {children}
    </dialog>
  );
}
