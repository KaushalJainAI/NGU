import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

/**
 * Password strength meter. Scores 0-4 on length + character variety and
 * penalises the obvious junk (all one class, repeated chars, common words),
 * so "password1" doesn't read as strong just for being 9 characters.
 */
export function scorePassword(password: string): number {
  if (!password) return 0;

  const COMMON = [
    "password", "12345678", "qwerty", "abc123", "111111", "iloveyou",
    "admin", "welcome", "letmein", "monkey", "dragon", "nidhi", "masala",
  ];
  const lower = password.toLowerCase();
  if (COMMON.some((c) => lower.includes(c))) return password.length >= 12 ? 1 : 0;

  // A single repeated character is never strong, however long.
  if (/^(.)\1+$/.test(password)) return 0;

  let score = 0;
  if (password.length >= 8) score += 1;
  if (password.length >= 12) score += 1;

  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) =>
    re.test(password),
  ).length;
  if (classes >= 2) score += 1;
  if (classes >= 3) score += 1;

  if (password.length < 8) score = Math.min(score, 1);

  return Math.min(score, 4);
}

interface PasswordStrengthProps {
  password: string;
  className?: string;
}

const PasswordStrength = ({ password, className }: PasswordStrengthProps) => {
  const { t } = useTranslation();
  const score = useMemo(() => scorePassword(password), [password]);

  if (!password) return null;

  const labels = [
    t("password.veryWeak"),
    t("password.weak"),
    t("password.fair"),
    t("password.good"),
    t("password.strong"),
  ];
  const colors = [
    "bg-destructive",
    "bg-destructive",
    "bg-yellow-500",
    "bg-lime-500",
    "bg-green-600",
  ];

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex gap-1" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={cn(
              "h-1 flex-1 rounded-full transition-colors",
              i < score ? colors[score] : "bg-muted",
            )}
          />
        ))}
      </div>
      <p
        className="text-xs text-muted-foreground"
        role="status"
        aria-live="polite"
      >
        {t("password.strengthLabel")}:{" "}
        <span className="font-medium text-foreground">{labels[score]}</span>
      </p>
    </div>
  );
};

export default PasswordStrength;
