import "../design-tokens.css";
import "../brand.css";

/** Approved PRUMO lettering is outlined so the logo never depends on a font. */
export function PrumoBrand({ className = "" }: { className?: string }) {
  return (
    <svg className={`prumo-brand ${className}`} viewBox="0 0 1102 276" width="1102" height="276" role="img" aria-label="PRUMO" fillRule="evenodd" focusable="false">
      <path className="prumo-ink" d="M69 0h16v100H69z"/><path className="prumo-accent" d="M37 108h80l35 45-76 123L0 153z"/><path className="prumo-ink" d="M205 76H285C325 76 348 99 348 138C348 176 324 201 285 201H249V246H205ZM249 116H275C292 116 300 124 300 139C300 154 291 162 275 162H249Z"/><path className="prumo-ink" d="M369 76H456C493 76 514 99 514 137C514 162 504 179 484 190L517 246H465L434 198H414V246H369ZM414 116H445C461 116 468 123 468 136C468 150 459 158 445 158H414Z"/><path className="prumo-ink" d="M538 76H583V174C583 197 594 208 614 208C635 208 645 197 645 174V76H690V176C690 222 662 249 614 249C565 249 538 223 538 177Z"/><path className="prumo-ink" d="M715 76H760L807 154L853 76H898V246H854V159L817 213H796L759 159V246H715Z"/><path className="prumo-ink" d="M1010 72C1062 72 1100 110 1100 161C1100 212 1062 250 1010 250C957 250 919 212 919 161C919 110 957 72 1010 72ZM1010 116C982 116 965 134 965 161C965 188 982 207 1010 207C1037 207 1053 188 1053 161C1053 134 1037 116 1010 116Z"/>
    </svg>
  );
}
