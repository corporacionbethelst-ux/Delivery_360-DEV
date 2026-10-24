import * as z from 'zod';

// Shared contract used by the registration form and its regression tests.
export const riderFormSchema = z.object({
  fullName: z.string().min(3, 'El nombre completo es requerido'),
  email: z.string().email('Email inválido'),
  phone: z.string().min(8, 'Teléfono inválido'),
  cpf: z.string().min(9, 'CPF/Documento requerido'),
  birthDate: z.string().min(1, 'Fecha de nacimiento requerida'),
  vehicleOwnershipType: z.enum(['PROPIO', 'EMPRESA']).default('PROPIO'),
  vehicleType: z.enum(['MOTO', 'BICICLETA', 'AUTO', 'PIE', 'NO_ESPECIFICADO']),
  vehiclePlate: z.string().optional(),
  assignedVehicleId: z.string().optional(),
  operatingZone: z.string().min(1, 'Zona requerida'),
  password: z.string().min(6, 'La contraseña debe tener al menos 6 caracteres'),
});
