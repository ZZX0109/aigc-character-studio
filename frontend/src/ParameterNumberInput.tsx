import { useEffect, useRef, useState } from 'react';

interface Props {
  value: number;
  onChange: (value: number) => void;
  disabled: boolean;
}

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
const clamp = (value: number) => Math.max(-1, Math.min(1, value));
const rounded = (value: number) => Math.round(clamp(value) * 100) / 100;
const display = (value: number) => value.toFixed(2);

/** Keep incomplete typing local; only finite, in-range values reach geometry state. */
export default function ParameterNumberInput({ value, onChange, disabled }: Props) {
  const [draft, setDraft] = useState(() => display(value));
  const lastEmitted = useRef<number | null>(null);

  useEffect(() => {
    // A parent echo must not replace "-0." or move the caret while typing.
    if (lastEmitted.current !== null && value === lastEmitted.current) {
      lastEmitted.current = null;
      return;
    }
    setDraft(display(value));
  }, [value]);

  function emit(next: number) {
    lastEmitted.current = next;
    onChange(next);
  }

  function commit() {
    const text = draft.trim();
    const parsed = DECIMAL.test(text) ? Number(text) : NaN;
    const next = Number.isFinite(parsed) ? rounded(parsed) : value;
    setDraft(display(next));
    emit(next);
  }

  return <input
    id="nose-width-value"
    aria-label="鼻翼宽度调整量数值"
    type="text"
    inputMode="decimal"
    role="spinbutton"
    aria-valuemin={-1}
    aria-valuemax={1}
    aria-valuenow={value}
    title="范围 −1 到 +1。回车确认，Esc 恢复有效数值，方向键微调。"
    value={draft}
    disabled={disabled}
    autoComplete="off"
    spellCheck={false}
    onChange={event => {
      const text = event.target.value;
      setDraft(text);
      const trimmed = text.trim();
      const parsed = DECIMAL.test(trimmed) ? Number(trimmed) : NaN;
      if (Number.isFinite(parsed) && parsed >= -1 && parsed <= 1) emit(parsed);
    }}
    onBlur={commit}
    onKeyDown={event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        event.currentTarget.blur();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        lastEmitted.current = null;
        setDraft(display(value));
      } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        event.preventDefault();
        const step = event.shiftKey ? 0.1 : 0.01;
        const next = rounded(value + (event.key === 'ArrowUp' ? step : -step));
        setDraft(display(next));
        emit(next);
      }
    }}
  />;
}
