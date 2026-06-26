import type { ParamField } from "../types";

interface Props {
  fields: ParamField[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled?: boolean;
}

export default function ParamFields({ fields, values, onChange, disabled }: Props) {
  const groups = [...new Set(fields.map((f) => f.group))];

  return (
    <>
      {groups.map((group) => (
        <div key={group}>
          <div className="param-group-title">{group}</div>
          {fields
            .filter((f) => f.group === group && f.key !== "goal")
            .map((field) => (
              <Field
                key={field.key}
                field={field}
                value={values[field.key]}
                onChange={(v) => onChange(field.key, v)}
                disabled={disabled}
              />
            ))}
        </div>
      ))}
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
    return (
      <div className="field">
        <label>{field.label}</label>
        <input
          type="number"
          step={field.type === "float" ? 0.01 : 1}
          min={field.min}
          max={field.max}
          value={value as number}
          disabled={disabled}
          onChange={(e) =>
            onChange(
              field.type === "float"
                ? parseFloat(e.target.value)
                : parseInt(e.target.value, 10)
            )
          }
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
