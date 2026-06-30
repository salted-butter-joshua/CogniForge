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
    const numValue =
      typeof value === "number" && Number.isFinite(value)
        ? value
        : (field.default as number);
    const step =
      field.step ?? (field.type === "float" ? 0.01 : 1);
    return (
      <div className="field">
        <label>{field.label}</label>
        <input
          type="number"
          step={step}
          min={field.min}
          max={field.max}
          value={numValue}
          disabled={disabled}
          onChange={(e) => {
            const raw = e.target.value.trim();
            if (raw === "") return;
            const parsed =
              field.type === "float" ? parseFloat(raw) : parseInt(raw, 10);
            if (!Number.isFinite(parsed)) return;
            if (field.min != null && parsed < field.min) return;
            if (field.max != null && parsed > field.max) return;
            onChange(parsed);
          }}
        />
        <div className="field-hint">{field.description}</div>
      </div>
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
