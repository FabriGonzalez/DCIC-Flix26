/** Flecha dibujada en SVG: los caracteres "←" o "‹" dependen de la fuente y se ven finos y desalineados. */
export function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={direction === "left" ? "M15 18l-6-6 6-6" : "M9 6l6 6-6 6"} />
    </svg>
  );
}
