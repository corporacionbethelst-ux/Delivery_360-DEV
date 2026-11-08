import * as z from "zod";

// Shared contract used by the registration form and its regression tests.
export const riderFormSchema = z
  .object({
    fullName: z
      .string()
      .trim()
      .min(3, "El nombre completo es requerido")
      .refine(
        (value) => value.split(/\s+/).length >= 2,
        "Incluye nombre y apellido",
      )
      .refine((value) => {
        const parts = value.split(/\s+/);
        return parts[0].length <= 100 && parts.slice(1).join(" ").length <= 100;
      }, "Nombre o apellido demasiado largo"),
    email: z.string().trim().email("Email inválido"),
    phone: z.string().trim().min(8, "Teléfono inválido"),
    cpf: z
      .string()
      .trim()
      .min(9, "CPF/Documento requerido")
      .max(14, "El documento debe tener hasta 14 caracteres"),
    vehicleOwnershipType: z.enum(["PROPIO", "EMPRESA"]).default("PROPIO"),
    vehicleType: z.enum([
      "MOTO",
      "BICICLETA",
      "AUTO",
      "PIE",
      "NO_ESPECIFICADO",
    ]),
    vehiclePlate: z.string().optional(),
    assignedVehicleId: z.string().optional(),
    operatingZone: z.string().trim().min(1, "Zona requerida"),
    password: z
      .string()
      .min(8, "La contraseña debe tener al menos 8 caracteres")
      .refine(
        (value) => value.trim().length > 0,
        "La contraseña no puede contener solo espacios",
      ),
  })
  .refine(
    (data) =>
      data.vehicleOwnershipType !== "EMPRESA" || !!data.assignedVehicleId,
    {
      path: ["assignedVehicleId"],
      message: "Selecciona un vehículo de empresa",
    },
  );
