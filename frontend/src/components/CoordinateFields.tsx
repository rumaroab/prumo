import { useEffect, useId, useState } from "react";

type Props = {
  value: [number, number] | null;
  onCommit: (value: [number, number]) => void;
  onValidityChange?: (valid: boolean) => void;
  onEdit?: () => void;
  disabled?: boolean;
};

export function validCoordinates(value: [number, number] | null): value is [number, number] {
  return Boolean(value && value.every(Number.isFinite) && Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 90);
}

/** Keep unfinished typing out of the geographic state, including empty inputs. */
export function CoordinateFields({ value, onCommit, onValidityChange, onEdit, disabled }: Props) {
  const [draft, setDraft] = useState<[string, string]>([String(value?.[0] ?? ""), String(value?.[1] ?? "")]);
  const [error, setError] = useState("");
  const id = useId();
  useEffect(() => {
    setDraft([String(value?.[0] ?? ""), String(value?.[1] ?? "")]);
    setError("");
    onValidityChange?.(validCoordinates(value));
  }, [value]);
  function parsed(values: [string, string]): [number, number] | null {
    if (values.some(item => !item.trim())) return null;
    const point: [number, number] = [Number(values[0].replace(",", ".")), Number(values[1].replace(",", "."))];
    return validCoordinates(point) ? point : null;
  }
  function commit() {
    const point = parsed(draft);
    onValidityChange?.(Boolean(point));
    if (!point) { setError("Introduza longitude entre −180 e 180 e latitude entre −90 e 90."); return; }
    setError("");
    onCommit(point);
  }
  return <fieldset className="coordinate-editor" disabled={disabled}>
    <legend>Coordenadas</legend>
    <div className="form-field-grid">
      {(["Longitude", "Latitude"] as const).map((label, index) => <label key={label} htmlFor={`${id}-${index}`}>
        {label}
        <input id={`${id}-${index}`} inputMode="decimal" type="text" value={draft[index]}
          aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : `${id}-hint`}
          onChange={event => {
            const next: [string, string] = [...draft]; next[index] = event.target.value;
            setDraft(next); setError(""); onEdit?.(); onValidityChange?.(Boolean(parsed(next)));
          }} onBlur={commit} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); commit(); } }} />
      </label>)}
    </div>
    <small id={`${id}-hint`}>Confirme com Enter ou ao sair do campo. Também pode escolher o ponto no mapa.</small>
    {error && <p id={`${id}-error`} className="failure" role="alert">{error}</p>}
  </fieldset>;
}
