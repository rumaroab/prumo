import { Box, Card, Typography } from "./components/ui";
import { t } from "./locale";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type LoadingOperation = { id: number; label: string };
type LoadingContextValue = {
  begin: (label: string) => () => void;
  isLoading: boolean;
};

const LoadingContext = createContext<LoadingContextValue | null>(null);

function afterPaint(callback: () => void) {
  requestAnimationFrame(() => requestAnimationFrame(callback));
}

export function LoadingProvider({ children }: { children: ReactNode }) {
  const [operations, setOperations] = useState<LoadingOperation[]>([]);
  const nextId = useRef(0);
  const overlay = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const isLoading = operations.length > 0;

  const begin = useCallback((label: string) => {
    const id = ++nextId.current;
    let finished = false;
    setOperations((current) => [...current, { id, label }]);
    return () => {
      if (finished) return;
      finished = true;
      afterPaint(() =>
        setOperations((current) =>
          current.filter((operation) => operation.id !== id),
        ),
      );
    };
  }, []);

  useEffect(() => {
    if (isLoading) {
      previousFocus.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      overlay.current?.focus();
      return;
    }
    const target = previousFocus.current;
    previousFocus.current = null;
    if (target?.isConnected) target.focus({ preventScroll: true });
  }, [isLoading]);

  const value = useMemo(() => ({ begin, isLoading }), [begin, isLoading]);
  const label = operations.at(-1)?.label || t("Loading…");

  return (
    <LoadingContext.Provider value={value}>
      <Box
        className="loading-content"
        inert={isLoading || undefined}
        aria-hidden={isLoading || undefined}
      >
        {children}
      </Box>
      {isLoading && (
        <Box
          ref={overlay}
          className="loading-overlay"
          role="status"
          aria-live="assertive"
          aria-busy="true"
          tabIndex={-1}
        >
          <LoadingIllustration />
          <strong>{label}</strong>
          <Typography as="small" variant="small">
            {t("Please wait while the workspace updates.")}
          </Typography>
        </Box>
      )}
    </LoadingContext.Provider>
  );
}

function LoadingIllustration() {
  return (
    <svg className="loading-illustration" viewBox="0 0 180 112" aria-hidden="true" focusable="false">
      <path className="loading-ground" d="M12 89 Q90 79 168 89" />
      <path className="loading-tree" d="M28 83V37m-15 33 15-31 15 31zm0-18-11 17h22zM135 83V27m-20 41 20-39 20 39zm20-23-13 24h26z" />
      <path className="loading-flame" d="M80 86c-13-10-10-22-2-29 1 7 6 9 6 9-2-12 8-20 14-27-1 11 8 16 8 28 0 11-8 19-20 19z" />
      <path className="loading-water" d="M163 65C143 28 115 31 96 57" />
      <circle className="loading-nozzle" cx="163" cy="65" r="4" />
    </svg>
  );
}

export function ScenarioLoading({ label }: { label: string }) {
  return (
    <main className="scenario-loading" role="status" aria-live="polite">
      <Card shadow="raised" className="scenario-loading-card">
        <LoadingIllustration />
        <Typography as="h1" variant="h3">{label}</Typography>
        <Typography as="p" variant="small" tone="muted">
          A preparar os mapas e os dados da ocorrência.
        </Typography>
      </Card>
    </main>
  );
}

export function useLoading() {
  const value = useContext(LoadingContext);
  if (!value) throw new Error("useLoading must be used inside LoadingProvider");
  return value;
}

export function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
