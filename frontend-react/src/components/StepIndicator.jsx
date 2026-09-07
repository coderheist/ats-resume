import { motion } from "framer-motion";
import { Check } from "lucide-react";

export function StepIndicator({ steps, current }) {
  return (
    <div className="step-indicator">
      {steps.map((label, i) => {
        const stepNum = i + 1;
        const state = stepNum < current ? "done" : stepNum === current ? "active" : "upcoming";
        return (
          <div key={label} className={`step-item step-${state}`}>
            <motion.div
              className="step-dot"
              animate={{ scale: state === "active" ? 1.12 : 1 }}
              transition={{ duration: 0.25, ease: "easeOut" }}
            >
              {state === "done" ? <Check size={13} /> : stepNum}
            </motion.div>
            <span className="step-label">{label}</span>
            {i < steps.length - 1 && <span className={`step-connector ${state === "done" ? "done" : ""}`} />}
          </div>
        );
      })}
    </div>
  );
}
