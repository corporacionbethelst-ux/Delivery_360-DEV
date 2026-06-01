import { UserRole } from '@/types/user';
import { 
  LayoutDashboard, Package, Users, MapPin, DollarSign, FileText, Settings, 
  Bike, ClipboardList, AlertTriangle, Truck, Shield, Wallet, PieChart, 
  Bell, History, CreditCard, Globe, Activity
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  roles: UserRole[];
  badge?: string;
  children?: NavItem[];
}

export const NAVIGATION_CONFIG: NavItem[] = [
  {
    label: 'Dashboard',
    href: '/manager',
    icon: LayoutDashboard,
    roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR', 'REPARTIDOR'],
  },
  {
    label: 'Operaciones',
    href: '/manager/operations',
    icon: Truck,
    roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR'],
    children: [
      { label: 'Órdenes', href: '/manager/operations/orders', icon: Package, roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR'] },
      { label: 'Entregas', href: '/manager/operations/deliveries', icon: ClipboardList, roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR'] },
      { label: 'Mapa en Vivo', href: '/manager/operations/live-map', icon: MapPin, roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR'] },
      { label: 'Alertas', href: '/manager/operations/alerts', icon: AlertTriangle, roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR'] },
    ]
  },
  {
    label: 'Flota',
    href: '/manager/fleet',
    icon: Bike,
    roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR'],
    children: [
      { label: 'Repartidores', href: '/manager/fleet/riders', icon: Users, roles: ['SUPERADMIN', 'GERENTE', 'OPERADOR'] },
      { label: 'Vehículos', href: '/manager/fleet/vehicles', icon: Truck, roles: ['SUPERADMIN', 'GERENTE'] },
      { label: 'Zonas', href: '/manager/fleet/zones', icon: Globe, roles: ['SUPERADMIN', 'GERENTE'] },
    ]
  },
  {
    label: 'Finanzas',
    href: '/manager/financial',
    icon: DollarSign,
    roles: ['SUPERADMIN', 'GERENTE'],
    children: [
      { label: 'Resumen', href: '/manager/financial/resumen', icon: LayoutDashboard, roles: ['SUPERADMIN', 'GERENTE'] },
      { label: 'Transacciones', href: '/manager/financial/transactions', icon: CreditCard, roles: ['SUPERADMIN', 'GERENTE'] },
      { label: 'Pagos a Riders', href: '/manager/financial/payouts', icon: Wallet, roles: ['SUPERADMIN', 'GERENTE'] },
      { label: 'Reportes', href: '/manager/financial/reports', icon: PieChart, roles: ['SUPERADMIN', 'GERENTE'] },
    ]
  },
  {
    label: 'Administración',
    href: '/manager/admin',
    icon: Shield,
    roles: ['SUPERADMIN'],
    children: [
      { label: 'Usuarios', href: '/manager/admin/users', icon: Users, roles: ['SUPERADMIN'] },
      { label: 'Roles', href: '/manager/admin/roles', icon: Shield, roles: ['SUPERADMIN'] },
      { label: 'Auditoría', href: '/manager/admin/audit', icon: History, roles: ['SUPERADMIN'] },
      { label: 'Configuración', href: '/manager/admin/settings', icon: Settings, roles: ['SUPERADMIN'] },
    ]
  },
  {
    label: 'Mis Entregas',
    href: '/rider/my-orders',
    icon: Package,
    roles: ['REPARTIDOR'],
  },
  {
    label: 'Mis Ganancias',
    href: '/rider/earnings',
    icon: Wallet,
    roles: ['REPARTIDOR'],
  },
];