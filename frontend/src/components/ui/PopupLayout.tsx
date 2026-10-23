import { useId, type ReactNode } from "react";
import "../../popup-layout.css";
import { Button } from "./Button";
import { Card } from "./Card";
import { Typography } from "./Typography";

export type PopupLayoutProps = {
  title: string;
  eyebrow?: string;
  onClose?: () => void;
  closeDisabled?: boolean;
  children: ReactNode;
  map?: ReactNode;
  navigation?: ReactNode;
  actions?: ReactNode;
  feedback?: ReactNode;
  size?: "compact" | "wide" | "drawer";
  className?: string;
};

/** One scroll region for fields; the header, map and actions retain their space. */
export function PopupLayout({ title, eyebrow, onClose, closeDisabled, children,
  map, navigation, actions, feedback, size = "compact", className = "" }: PopupLayoutProps) {
  const titleId = useId();
  return (
    <Card as="section" shadow="raised" aria-labelledby={titleId}
      className={`popup-layout popup-layout--${map ? "map" : size} ${className}`}>
      <header className="popup-heading">
        <div>
          {eyebrow && <Typography as="span" variant="label">{eyebrow}</Typography>}
          <Typography as="h2" variant="h3" id={titleId}>{title}</Typography>
        </div>
        {onClose && <Button variant="ghost" disabled={closeDisabled} onClick={onClose} aria-label="Fechar janela">Fechar</Button>}
      </header>
      {navigation && <div className="popup-navigation">{navigation}</div>}
      <div className={`popup-content${map ? " popup-content--map" : ""}`}>
        <div className="popup-fields">{children}</div>
        {map && <div className="popup-map">{map}</div>}
      </div>
      {(actions || feedback) && <footer className="popup-footer">
        {feedback && <div className="popup-feedback">{feedback}</div>}
        {actions && <div className="popup-actions">{actions}</div>}
      </footer>}
    </Card>
  );
}
