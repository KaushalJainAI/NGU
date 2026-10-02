import React, { useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { authAPI } from "@/lib/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentEmail: string;
  /** Called with the new address once the backend has switched it. */
  onChanged: (newEmail: string) => void;
}

/**
 * Two-step login-email change: (1) new address + current password → a code is
 * mailed to the NEW address; (2) that code confirms it. The login email cannot
 * be edited through the profile form — the backend rejects it there.
 */
const ChangeEmailDialog: React.FC<Props> = ({ open, onOpenChange, currentEmail, onChanged }) => {
  const { t } = useTranslation();
  const [step, setStep] = useState<"details" | "code">("details");
  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  const reset = () => {
    setStep("details");
    setNewEmail("");
    setPassword("");
    setCode("");
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsBusy(true);
    try {
      if (step === "details") {
        await authAPI.changeEmail(newEmail.trim(), password);
        toast.success(t("changeEmail.codeSent", { email: newEmail.trim() }));
        setStep("code");
      } else {
        await authAPI.changeEmail(newEmail.trim(), password, code);
        toast.success(t("changeEmail.success"));
        onChanged(newEmail.trim().toLowerCase());
        handleOpenChange(false);
      }
    } catch (error: any) {
      toast.error(error?.message || t("changeEmail.failed"));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("changeEmail.title")}</DialogTitle>
          <DialogDescription>
            {step === "details"
              ? t("changeEmail.description", { email: currentEmail })
              : t("changeEmail.codeDescription", { email: newEmail.trim() })}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {step === "details" ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="newEmail">{t("changeEmail.newEmail")}</Label>
                <Input
                  id="newEmail"
                  type="email"
                  autoComplete="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="changeEmailPassword">{t("changeEmail.currentPassword")}</Label>
                <Input
                  id="changeEmailPassword"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <p className="text-xs text-muted-foreground">{t("changeEmail.googleHint")}</p>
              </div>
            </>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="changeEmailCode">{t("changeEmail.code")}</Label>
              <Input
                id="changeEmailCode"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                required
                className="text-center text-lg tracking-[0.5em]"
              />
            </div>
          )}
          <DialogFooter>
            {step === "code" && (
              <Button type="button" variant="ghost" onClick={() => setStep("details")} disabled={isBusy}>
                {t("changeEmail.back")}
              </Button>
            )}
            <Button type="submit" disabled={isBusy || (step === "code" && code.length !== 6)}>
              {step === "details" ? t("changeEmail.sendCode") : t("changeEmail.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default ChangeEmailDialog;
