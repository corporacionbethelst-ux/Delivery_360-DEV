import type { FailureCause } from "@/services/delivery.service";

// Definición completa de causas estandarizadas
export interface FailureOption {
  value: FailureCause;
  label: string;
  bonificable: boolean;
}

export const FAILURE_CAUSES: FailureOption[] = [
  // --- Causas Bonificables (Culpa del Cliente / Externas) ---
  {
    value: "CLIENTE_NO_ESTA",
    label: "El cliente no estaba en el lugar",
    bonificable: true,
  },
  {
    value: "CLIENTE_NO_CONTESTA",
    label: "El cliente no contesta llamadas/timbre",
    bonificable: true,
  },
  {
    value: "DIRECCION_INCORRECTA",
    label: "La dirección proporcionada es incorrecta",
    bonificable: true,
  },
  {
    value: "DIRECCION_NO_EXISTE",
    label: "La dirección no existe / No se encuentra",
    bonificable: true,
  },
  {
    value: "COMERCIO_CERRADO",
    label: "El comercio estaba cerrado",
    bonificable: true,
  },
  {
    value: "CLIENTE_RECHAZA",
    label: "El cliente rechazó el pedido",
    bonificable: true,
  },
  {
    value: "ZONA_INSEGURA",
    label: "La zona se tornó insegura",
    bonificable: true,
  },
  {
    value: "FUERZA_MAYOR",
    label: "Fuerza mayor (clima, eventos, etc.)",
    bonificable: true,
  },
  {
    value: "EDIFICIO_RESTRINGIDO",
    label: "Acceso restringido en edificio/conjunto",
    bonificable: true,
  },

  // --- Causas NO Bonificables (Culpa del Repartidor) ---
  {
    value: "REPARTIDOR_NO_QUIERE_ENTREGAR",
    label: "Repartidor no quiere entregar (sin causa justa)",
    bonificable: false,
  },
  {
    value: "REPARTIDOR_LLEGO_TARDE",
    label: "Repartidor llegó tarde",
    bonificable: false,
  },
  {
    value: "REPARTIDOR_ERROR_PROPIO",
    label: "Error operativo del repartidor",
    bonificable: false,
  },
  {
    value: "REPARTIDOR_VEHICULO_FALLA",
    label: "Falla mecánica del vehículo",
    bonificable: false,
  },
  {
    value: "REPARTIDOR_SIN_BATERIA",
    label: "Celular sin batería / Apagado",
    bonificable: false,
  },
  {
    value: "OTRO_REPARTIDOR",
    label: "Entregada por otro repartidor",
    bonificable: false,
  },
];

