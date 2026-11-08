"use client";
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, UserPlus } from "lucide-react";
import RiderRegistrationForm from "@/components/riders/RiderRegistrationForm";
import { ManagerPageBoundary } from "@/components/layout/ManagerPageBoundary";
import {
  OperationsHeader,
  operationStyles,
} from "@/components/operations/OperationsUI";
import { cn } from "@/lib/utils";
export default function ManagerCreateRiderPage() {
  return (
    <ManagerPageBoundary scope="rider-registration">
      <RegistrationScreen />
    </ManagerPageBoundary>
  );
}
function RegistrationScreen() {
  const router = useRouter();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const timers = timer;
    return () => {
      if (timers.current) clearTimeout(timers.current);
    };
  }, []);
  const cancel = () => router.back();
  return (
    <div className={cn(operationStyles.page, "max-w-3xl")}>
      <OperationsHeader
        icon={UserPlus}
        eyebrow="Flota · Registro"
        title="Nuevo Repartidor"
        description="Registra un nuevo miembro de la flota con sus datos y vehículo."
        actions={
          <button className={operationStyles.button} onClick={cancel}>
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            Volver
          </button>
        }
      />
      <RiderRegistrationForm
        onSuccess={() => {
          timer.current = setTimeout(
            () => router.push("/manager/fleet/riders"),
            1000,
          );
        }}
        onCancel={cancel}
      />
    </div>
  );
}
