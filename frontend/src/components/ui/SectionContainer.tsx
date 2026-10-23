import {
  createElement,
  forwardRef,
  type ComponentPropsWithoutRef,
} from "react";
import "../../design-tokens.css";

export type SectionContainerProps = ComponentPropsWithoutRef<"section"> & {
  as?: "section" | "main" | "div" | "footer";
  spacing?: "default" | "compact";
  /** Layout classes for the inner container, e.g. ds-stack. */
  containerClassName?: string;
};

export const SectionContainer = forwardRef<HTMLElement, SectionContainerProps>(
  function SectionContainer(
    {
      children,
      as = "section",
      spacing = "default",
      className,
      containerClassName,
      ...props
    },
    ref,
  ) {
    return createElement(
      as,
      {
        ...props,
        ref,
        "data-ui": "section",
        "data-spacing": spacing,
        className: ["ds-section", "ds-surface", className]
          .filter(Boolean)
          .join(" "),
      },
      <div
        className={["ds-container", containerClassName]
          .filter(Boolean)
          .join(" ")}
      >
        {children}
      </div>,
    );
  },
);
