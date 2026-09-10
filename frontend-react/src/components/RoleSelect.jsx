/**
 * Target-role picker for the JD-less report.
 *
 * The empty value is the default and means "infer it from my resume",
 * which is the behaviour that existed before this control. It is worth
 * offering the choice because inference rests on two things that can
 * each be wrong -- how much the parser extracted, and how well a fixed
 * tech ontology describes this person -- and a sparse parse leaves
 * several roles tied on the same generic skills. Naming the role removes
 * that guesswork, and asks the more useful question anyway: readiness
 * for the job you actually want, rather than a label for the resume as
 * it currently reads.
 */
export function RoleSelect({ roles, value, onChange, disabled = false }) {
  // Nothing to choose from: the list failed to load (see useRoles), so
  // render nothing and let the backend infer, rather than showing an
  // empty control that looks broken.
  if (!roles.length) return null;

  return (
    <div className="role-select">
      <label htmlFor="target-role">Target role</label>
      <select
        id="target-role"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Infer from my resume</option>
        {roles.map((role) => (
          <option key={role.id} value={role.id}>
            {role.label}
          </option>
        ))}
      </select>
      <p className="role-select-hint">
        {value
          ? "Skill coverage is measured against this role."
          : "We'll guess the role from your skills. Pick one for a more accurate gap list."}
      </p>
    </div>
  );
}
