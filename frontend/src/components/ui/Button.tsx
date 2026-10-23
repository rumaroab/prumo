import { forwardRef, type ComponentPropsWithoutRef } from "react";
import "../../design-tokens.css";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";
export type ButtonIntent = "default" | "danger";

export type ButtonProps = ComponentPropsWithoutRef<"button"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  intent?: ButtonIntent;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      size = "md",
      intent = "default",
      type = "button",
      disabled = false,
      "aria-disabled": ariaDisabled,
      className,
      ...props
    },
    ref,
  ) {
    // Use native disabled behavior for both APIs, including keyboard activation.
    const isDisabled =
      disabled || ariaDisabled === true || ariaDisabled === "true";

    return (
      <button
        {...props}
        ref={ref}
        type={type}
        disabled={isDisabled}
        aria-disabled={isDisabled || undefined}
        data-ui="button"
        data-variant={variant}
        data-size={size}
        data-intent={intent}
        className={[
          "ds-button",
          `ds-button-${variant}`,
          `ds-button-${size}`,
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      />
    );
  },
);
