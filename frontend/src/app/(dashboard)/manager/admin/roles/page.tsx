'use client';

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Shield, Plus, Edit, Trash2, Lock, Users, Copy, Save, X, AlertTriangle, Loader2, CheckCircle } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { roleService, Role, Permission, RoleCreateInput } from '@/services/role.service';

// Fallback de permisos si el backend no los devuelve
const FALLBACK_PERMISSIONS: Permission[] = [
  { id: 'view_orders', name: 'Ver Órdenes', module: 'orders' },
  { id: 'create_orders', name: 'Crear Órdenes', module: 'orders' },
  { id: 'manage_riders', name: 'Gestionar Riders', module: 'riders' },
  { id: 'view_financial', name: 'Ver Finanzas', module: 'financial' },
  { id: 'manage_users', name: 'Gestionar Usuarios', module: 'users' },
  { id: 'system_settings', name: 'Configuración', module: 'admin' },
];

export default function AdminRolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>(FALLBACK_PERMISSIONS);
  const [loading, setLoading] = useState(true);
  
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [deletingRole, setDeletingRole] = useState<Role | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [formData, setFormData] = useState<RoleCreateInput>({ name: '', slug: '', description: '', permissions: [] });

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [rolesData, permsData] = await Promise.all([
        roleService.getAll(),
        roleService.getPermissions().catch(() => FALLBACK_PERMISSIONS)
      ]);
      setRoles(rolesData);
      setPermissions(permsData);
    } catch (err: any) {
      setError(err.message || 'Error al cargar datos');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = () => {
    setEditingRole(null);
    setFormData({ name: '', slug: '', description: '', permissions: [] });
    setIsDialogOpen(true);
  };

  const handleEdit = (role: Role) => {
    if (role.is_system) {
      // Si es sistema, lo duplicamos para editar
      setEditingRole(null); 
      setFormData({ 
        name: `${role.name} (Copia)`, 
        slug: `${role.slug}_copy`, // Asegúrate de que tu interfaz tenga 'slug' o quita esta línea si no existe
        description: role.description || '', // ✅ Solución correcta
        permissions: [...role.permissions] 
      });
    } else {
      setEditingRole(role);
      setFormData({ 
        name: role.name, 
        slug: role.slug, // Igual aquí
        description: role.description || '', // ✅ Solución correcta
        permissions: [...role.permissions] 
      });
    }
    setIsDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formData.name.trim()) {
      setError('El nombre es requerido');
      return;
    }
    if (!formData.slug.trim()) {
       // Generar slug simple si no existe
       formData.slug = formData.name.toUpperCase().replace(/ /g, '_');
    }

    setSaving(true);
    setError(null);

    try {
      if (editingRole) {
        await roleService.update(editingRole.id, formData);
      } else {
        await roleService.create(formData);
      }
      await loadData();
      setIsDialogOpen(false);
    } catch (err: any) {
      setError(err.message || 'Error al guardar el rol');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deletingRole) return;
    setSaving(true);
    try {
      await roleService.delete(deletingRole.id);
      await loadData();
      setDeletingRole(null);
    } catch (err: any) {
      alert('Error al eliminar: ' + (err.message || 'No se pudo eliminar'));
      setSaving(false);
    }
  };

  const togglePermission = (permId: string) => {
    setFormData(prev => ({
      ...prev,
      permissions: prev.permissions.includes(permId)
        ? prev.permissions.filter(id => id !== permId)
        : [...prev.permissions, permId]
    }));
  };

  const permissionsByModule = permissions.reduce((acc, perm) => {
    acc[perm.module] = acc[perm.module] || [];
    acc[perm.module].push(perm);
    return acc;
  }, {} as Record<string, Permission[]>);

  if (loading && roles.length === 0) {
    return <div className="flex h-screen items-center justify-center"><Loader2 className="animate-spin h-10 w-10" /></div>;
  }

  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <div className="max-w-5xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Shield className="w-6 h-6 text-indigo-600" />
              Roles y Permisos
            </h1>
            <p className="text-gray-500 mt-1">Define niveles de acceso y capacidades del sistema</p>
          </div>
          <Button onClick={handleCreate} className="bg-indigo-600 hover:bg-indigo-700 shadow-md">
            <Plus className="w-4 h-4 mr-2" /> Nuevo Rol
          </Button>
        </div>

        {error && <Alert variant="destructive" className="mb-6"><AlertTriangle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>}

        <div className="space-y-4">
          {roles.map((role) => (
            <Card key={role.id} className={`border-l-4 transition-all hover:shadow-md ${role.is_system ? 'border-l-indigo-500 bg-white' : 'border-l-blue-400 bg-white'}`}>
              <CardHeader className="pb-3">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <CardTitle className="text-lg">{role.name}</CardTitle>
                      {role.is_system && (
                        <Badge variant="secondary" className="bg-indigo-100 text-indigo-700 border-indigo-200 text-[10px]">
                          <Lock className="w-3 h-3 mr-1" /> Sistema
                        </Badge>
                      )}
                    </div>
                    <CardDescription className="text-sm">{role.description}</CardDescription>
                  </div>
                  
                  <div className="flex items-center gap-4 pl-4 border-l ml-4">
                    <div className="text-right hidden sm:block">
                      <div className="text-2xl font-bold text-gray-900">{role.users_count || 0}</div>
                      <div className="text-xs text-gray-500 flex items-center justify-end gap-1">
                        <Users className="w-3 h-3" /> Usuarios
                      </div>
                    </div>
                    <div className="flex gap-1">
                      {!role.is_system ? (
                        <>
                          <Button variant="outline" size="icon" onClick={() => handleEdit(role)} title="Editar">
                            <Edit className="w-4 h-4" />
                          </Button>
                          <Button variant="outline" size="icon" onClick={() => setDeletingRole(role)} title="Eliminar" className="text-red-600 hover:text-red-700 hover:bg-red-50">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </>
                      ) : (
                        <Button variant="outline" size="icon" onClick={() => handleEdit(role)} title="Duplicar para editar">
                          <Copy className="w-4 h-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2 pt-2 border-t mt-2">
                  {role.permissions.slice(0, 6).map(pid => {
                    const perm = permissions.find(p => p.id === pid);
                    return perm ? (
                      <Badge key={pid} variant="outline" className="text-xs bg-gray-50">{perm.name}</Badge>
                    ) : <Badge key={pid} variant="outline" className="text-xs">{pid}</Badge>;
                  })}
                  {role.permissions.length > 6 && (
                    <Badge variant="secondary" className="text-xs">+{role.permissions.length - 6} más</Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* Diálogo */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingRole ? 'Editar Rol' : 'Crear Nuevo Rol'}</DialogTitle>
            <DialogDescription>
              {editingRole ? 'Modifica los detalles y permisos del rol.' : 'Define un nuevo perfil de acceso.'}
            </DialogDescription>
          </DialogHeader>
          
          <div className="py-4 space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Nombre del Rol</Label>
                <Input 
                  id="name" 
                  value={formData.name} 
                  onChange={(e) => setFormData({...formData, name: e.target.value})}
                  placeholder="Ej: Supervisor" 
                />
              </div>
              <div className="space-y-2">
                <Label>Slug (ID interno)</Label>
                <Input 
                  value={formData.slug} 
                  onChange={(e) => setFormData({...formData, slug: e.target.value.toUpperCase().replace(/ /g, '_')})}
                  className="uppercase font-mono text-xs"
                  placeholder="AUTO_GENERADO"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="desc">Descripción</Label>
              <Textarea 
                id="desc" 
                value={formData.description || ''} 
                onChange={(e) => setFormData({...formData, description: e.target.value})}
                placeholder="Describe brevemente la función..." 
                rows={2}
              />
            </div>

            <div className="space-y-3">
              <Label className="text-base font-semibold">Permisos Detallados</Label>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {Object.entries(permissionsByModule).map(([module, perms]) => (
                  <div key={module} className="space-y-2">
                    <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider border-b pb-1 capitalize">
                      {module}
                    </h4>
                    <div className="space-y-2">
                      {perms.map(perm => (
                        <div key={perm.id} className="flex items-center justify-between group">
                          <span className="text-sm text-gray-700">{perm.name}</span>
                          <Switch 
                            checked={formData.permissions.includes(perm.id)}
                            onCheckedChange={() => togglePermission(perm.id)}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)} disabled={saving}>Cancelar</Button>
            <Button onClick={handleSave} disabled={saving} className="bg-indigo-600 hover:bg-indigo-700">
              {saving ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Guardando...</> : <><Save className="mr-2 h-4 w-4" /> Guardar Cambios</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Diálogo Eliminar */}
      <Dialog open={!!deletingRole} onOpenChange={() => setDeletingRole(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
              <AlertTriangle className="w-5 h-5" /> Eliminar Rol
            </DialogTitle>
            <DialogDescription>
              ¿Estás seguro de eliminar <strong>{deletingRole?.name}</strong>?
              <br/><span className="text-orange-600 text-sm">Esta acción no se puede deshacer.</span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeletingRole(null)} disabled={saving}>Cancelar</Button>
            <Button variant="destructive" onClick={handleDeleteConfirm} disabled={saving}>
              {saving ? 'Eliminando...' : 'Sí, eliminar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}