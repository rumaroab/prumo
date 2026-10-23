import { forwardRef, type ComponentPropsWithoutRef } from "react";
import type { ButtonVariant, ButtonSize } from "./Button";
import "../../design-tokens.css";

export type ButtonLinkProps = ComponentPropsWithoutRef<"a"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

/** A real anchor: preserves URLs, downloads, modified clicks and browser history. */
export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(
  function ButtonLink(
    { variant = "secondary", size = "md", className, ...props },
    ref,
  ) {
    return (
      <a
        {...props}
        ref={ref}
        data-ui="button-link"
        data-variant={variant}
        data-size={size}
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
