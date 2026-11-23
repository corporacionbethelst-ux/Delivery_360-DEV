"use client";

import { useEffect, useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { AlertCircle, ShieldQuestion } from "lucide-react";
import { Toaster } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { clearFeedback, dismissDialogs, feedbackSnapshot, settleFeedback, subscribeFeedback } from "@/lib/feedback";
import { onCredentialsChanged } from "@/lib/auth-session";

export function FeedbackHost() {
  const pathname = usePathname();
  useEffect(() => () => dismissDialogs(), [pathname]);
  const item = useSyncExternalStore(subscribeFeedback, feedbackSnapshot, () => null);
  useEffect(() => {
    const unsubscribe = onCredentialsChanged(clearFeedback);
    return () => { unsubscribe(); clearFeedback(); };
  }, []);
  const confirmation = item?.kind === "confirm";
  return <>
    <Toaster richColors closeButton position="bottom-right" offset={16} mobileOffset={16} containerAriaLabel="Notificaciones informativas"
      toastOptions={{ style: { zIndex: 9999 } }} />
    <Dialog open={!!item} onOpenChange={(open) => { if (!open && item) settleFeedback(item.id, false); }}>
      <DialogContent role="alertdialog" className="w-[calc(100vw-2rem)] sm:max-w-md max-h-[85dvh] overflow-y-auto rounded-xl border-slate-200">
        <DialogHeader>
          <div className={`mb-2 flex h-12 w-12 items-center justify-center rounded-xl ${confirmation || item?.tone === "warning" ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-600"}`}>
            {confirmation ? <ShieldQuestion className="h-6 w-6" /> : <AlertCircle className="h-6 w-6" />}
          </div>
          <DialogTitle>{item?.title}</DialogTitle>
          <DialogDescription className="whitespace-pre-wrap break-words pt-2 text-sm leading-6 text-slate-600">{item?.message}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:space-x-0">
          {confirmation && <Button variant="outline" autoFocus onClick={() => item && settleFeedback(item.id, false)}>Cancelar</Button>}
          <Button autoFocus={!confirmation} className="bg-blue-600 hover:bg-blue-700" onClick={() => item && settleFeedback(item.id, true)}>{confirmation ? "Confirmar" : "Entendido"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
