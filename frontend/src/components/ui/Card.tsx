import {
  createElement,
  forwardRef,
  type ComponentPropsWithRef,
  type ComponentPropsWithoutRef,
  type ForwardedRef,
  type ReactElement,
} from "react";
import "../../design-tokens.css";

export type CardShadow = "none" | "card" | "raised";
export type CardElement =
  | "div"
  | "section"
  | "article"
  | "aside"
  | "details"
  | "dialog"
  | "form";
export type CardProps<E extends CardElement = "div"> =
  ComponentPropsWithoutRef<E> & {
    as?: E;
    shadow?: CardShadow;
    density?: "default" | "compact";
  };

export const Card = forwardRef(function Card<E extends CardElement = "div">(
  {
    as,
    shadow = "card",
    density = "default",
    className,
    ...props
  }: CardProps<E>,
  ref: ForwardedRef<HTMLElement>,
) {
  return createElement(as ?? "div", {
    ...props,
    ref,
    "data-ui": "card",
    "data-shadow": shadow,
    "data-density": density,
    className: ["ds-card", `ds-shadow-${shadow}`, className]
      .filter(Boolean)
      .join(" "),
  });
}) as <E extends CardElement = "div">(
  props: CardProps<E> & { ref?: ComponentPropsWithRef<E>["ref"] },
) => ReactElement;
