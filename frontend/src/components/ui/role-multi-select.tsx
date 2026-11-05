"use client";

type Props = {
  options: string[];
  value: string[];
  onChange: (roles: string[]) => void;
  disabled?: boolean;
};

export function RoleMultiSelect({ options, value, onChange, disabled = false }: Props) {
  const allRoles = Array.from(new Set([...options, ...value])).sort();
  return <details className="rounded border border-gray-300 dark:border-dark-3">
    <summary className="cursor-pointer p-3">Roles: {value.length ? value.join(", ") : "None selected"}</summary>
    <fieldset disabled={disabled} aria-label="Assigned roles" className="max-h-56 space-y-2 overflow-y-auto border-t p-3">
      {allRoles.length === 0 && <p className="text-sm text-gray-500">No assignable roles available.</p>}
      {allRoles.map(role => <label key={role} className="flex cursor-pointer items-center gap-3">
        <input type="checkbox" checked={value.includes(role)} disabled={!options.includes(role)}
          onChange={event => onChange(event.target.checked ? [...value, role] : value.filter(name => name !== role))} />
        <span>{role}</span>
        {!options.includes(role) && <span className="text-xs text-gray-500">Outside your grant permissions</span>}
      </label>)}
    </fieldset>
  </details>;
}
