import { useEffect, useState } from "react";
import type { ParamField } from "../types";

interface Props {
  fields: ParamField[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled?: boolean;
}

export default function ParamFields({ fields, values, onChange, disabled }: Props) {
  const groups = [...new Set(fields.map((f) => f.group))];

  const visible = (field: ParamField) => {
    if (!field.visible_when_key) return true;
    return values[field.visible_when_key] === field.visible_when_equals;
  };

  return (
    <>
      {groups.map((group) => {
        const groupFields = fields.filter(
          (f) => f.group === group && f.key !== "goal" && visible(f)
        );
        if (groupFields.length === 0) return null;
        return (
          <div key={group}>
            <div className="param-group-title">{group}</div>
            {groupFields.map((field) => (
              <Field
                key={field.key}
                field={field}
                value={values[field.key]}
                onChange={(v) => onChange(field.key, v)}
                disabled={disabled}
              />
            ))}
          </div>
        );
      })}
    </>
  );
}

function clampNumber(value: number, field: ParamField): number {
  let out = value;
  if (field.min != null && out < field.min) out = field.min;
  if (field.max != null && out > field.max) out = field.max;
  return out;
}

function Field({
  field,
  value,
  onChange,
  disabled,
}: {
  field: ParamField;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
}) {
  if (field.type === "bool") {
    return (
      <div className="field field-row">
        <div>
          <label>{field.label}</label>
          <div className="field-hint">{field.description}</div>
        </div>
        <label className="toggle">
          <input
            type="checkbox"
            checked={Boolean(value)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span className="toggle-slider" />
        </label>
      </div>
    );
  }

  if (field.type === "float" || field.type === "int") {
    return (
      <NumberField
        field={field}
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    );
  }

  return (
    <div className="field">
      <label>{field.label}</label>
      <input
        type="text"
        value={String(value ?? "")}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="field-hint">{field.description}</div>
    </div>
  );
}

function NumberField({
  field,
  value,
  onChange,
  disabled,
}: {
  field: ParamField;
  value: unknown;
  onChange: (v: unknown) => void;
  disabled?: boolean;
}) {
  const resolved =
    typeof value === "number" && Number.isFinite(value)
      ? value
      : (field.default as number);
  const [focused, setFocused] = useState(false);
  const [text, setText] = useState(String(resolved));

  useEffect(() => {
    if (!focused) {
      setText(String(resolved));
    }
  }, [resolved, focused]);

  const step = field.step ?? (field.type === "float" ? 0.01 : 1);

  const commit = (raw: string) => {
    const trimmed = raw.trim();
    if (trimmed === "" || trimmed === "-" || trimmed === ".") {
      const fallback = clampNumber(resolved, field);
      onChange(fallback);
      setText(String(fallback));
      return;
    }
    const parsed =
      field.type === "float" ? parseFloat(trimmed) : parseInt(trimmed, 10);
    if (!Number.isFinite(parsed)) {
      setText(String(resolved));
      return;
    }
    const clamped = clampNumber(parsed, field);
    onChange(clamped);
    setText(String(clamped));
  };

  return (
    <div className="field">
      <label>{field.label}</label>
      <input
        type="number"
        step={step}
        min={field.min}
        max={field.max}
        value={text}
        disabled={disabled}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          commit(text);
        }}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          }
        }}
      />
      <div className="field-hint">{field.description}</div>
    </div>
  );
}
