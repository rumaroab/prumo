import { createElement, forwardRef, type HTMLAttributes } from "react";
import "../../design-tokens.css";

export type TypographyVariant =
  | "h1"
  | "h2"
  | "h3"
  | "body"
  | "subtitle"
  | "small"
  | "label";
export type TypographyElement =
  | "h1"
  | "h2"
  | "h3"
  | "h4"
  | "h5"
  | "h6"
  | "p"
  | "span"
  | "div"
  | "small";
export type TypographyProps = Omit<HTMLAttributes<HTMLElement>, "color"> & {
  variant?: TypographyVariant;
  /** Semantic element; independent of visual size. */
  as?: TypographyElement;
  tone?: "default" | "muted";
};

const elements: Record<TypographyVariant, TypographyElement> = {
  h1: "h1",
  h2: "h2",
  h3: "h3",
  body: "p",
  subtitle: "p",
  small: "small",
  label: "span",
};

export const Typography = forwardRef<HTMLElement, TypographyProps>(
  function Typography(
    {
      variant = "body",
      as,
      tone = variant === "subtitle" ? "muted" : "default",
      className,
      ...props
    },
    ref,
  ) {
    return createElement(as ?? elements[variant], {
      ...props,
      ref,
      "data-ui": "typography",
      "data-variant": variant,
      "data-tone": tone,
      className: [
        `ds-${variant}`,
        tone === "muted" && "ds-text-muted",
        className,
      ]
        .filter(Boolean)
        .join(" "),
    });
  },
);
