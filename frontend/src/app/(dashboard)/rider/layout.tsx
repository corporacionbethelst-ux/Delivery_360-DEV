"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useAuthStore } from "@/stores/authStore"
import { LogOut, User as UserIcon, Menu, X, Bike } from "lucide-react"
import { authService } from "@/services/auth.service"
import { Button } from "@/components/ui/button"

export default function RiderLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  
  const { user, isAuthenticated, logout: storeLogout } = useAuthStore()
  
  const [isMounted, setIsMounted] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)

  useEffect(() => {
    setIsMounted(true)
  }, [])

  const tabs = [
    { id: "dashboard", name: "Dashboard", href: "/rider" },
    { id: "orders", name: "Mis Órdenes", href: "/rider/my-orders" },
    { id: "earnings", name: "Ganancias", href: "/rider/earnings" },
    { id: "productivity", name: "Productividad", href: "/rider/productivity" },
    { id: "profile", name: "Perfil", href: "/rider/profile" },
  ]

  const handleLogout = async () => {
    if (isLoggingOut) return
    setIsLoggingOut(true)
    try {
      await authService.logout()
      storeLogout()
      window.location.href = "/login"
    } catch (error) {
      console.error("Error al cerrar sesión:", error)
      storeLogout()
      window.location.href = "/login"
    } finally {
      setIsLoggingOut(false)
    }
  }

  if (!isMounted || !isAuthenticated || !user) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  if (user.role !== 'REPARTIDOR') {
    return null
  }

  return (
    // Contenedor principal de altura completa sin scroll externo
    <div className="flex flex-col h-screen bg-gray-50 overflow-hidden">
      
      {/* Header Fijo en la parte superior del flex container */}
      <header className="bg-white shadow-sm border-b z-40 shrink-0">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-4">
              <div className="flex items-center justify-center w-8 h-8 bg-blue-600 rounded-lg text-white">
                <Bike className="w-5 h-5" />
              </div>
              <h1 className="text-xl font-bold text-blue-900 hidden sm:block">Delivery360 Rider</h1>
              
              {/* Info Usuario Desktop */}
              <div className="hidden md:flex items-center space-x-2 text-sm text-gray-600 bg-gray-100 px-3 py-1.5 rounded-full">
                <UserIcon className="w-4 h-4 text-gray-500" />
                <span className="font-medium capitalize truncate max-w-[200px]">
                  {user.first_name} {user.last_name}
                </span>
              </div>
            </div>
            
            <div className="flex items-center space-x-2 md:space-x-4">
              {/* Navegación Desktop */}
              <nav className="hidden md:flex space-x-1">
                {tabs.map((tab) => {
                  const isActive = pathname === tab.href || (tab.href !== "/rider" && pathname.startsWith(tab.href + "/"))
                  return (
                    <Link
                      key={tab.id}
                      href={tab.href}
                      className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                        isActive
                          ? "bg-blue-100 text-blue-900"
                          : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                      }`}
                    >
                      {tab.name}
                    </Link>
                  )
                })}
              </nav>

              {/* Botón Menú Móvil */}
              <button 
                className="md:hidden p-2 text-gray-600 hover:bg-gray-100 rounded-md"
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              >
                {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
              </button>

              {/* Botón Logout Desktop */}
              <button
                onClick={handleLogout}
                disabled={isLoggingOut}
                className="hidden md:flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 rounded-md transition-colors disabled:opacity-50"
              >
                <LogOut className="w-4 h-4" />
                {isLoggingOut ? "Saliendo..." : "Salir"}
              </button>
            </div>
          </div>
          
          {/* Menú Móvil Desplegable */}
          {mobileMenuOpen && (
            <div className="md:hidden border-t pt-4 pb-4 space-y-2 animate-in slide-in-from-top-2">
              <div className="flex items-center gap-3 px-4 py-2 mb-4 bg-gray-50 rounded-md">
                <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold">
                  {user.first_name.charAt(0)}{user.last_name.charAt(0)}
                </div>
                <div className="overflow-hidden">
                  <p className="font-bold text-gray-900 truncate">{user.first_name} {user.last_name}</p>
                  <p className="text-xs text-gray-500 truncate">{user.email}</p>
                </div>
              </div>
              
              <nav className="flex flex-col space-y-1 px-2">
                {tabs.map((tab) => {
                  const isActive = pathname === tab.href || (tab.href !== "/rider" && pathname.startsWith(tab.href + "/"))
                  return (
                    <Link
                      key={tab.id}
                      href={tab.href}
                      onClick={() => setMobileMenuOpen(false)}
                      className={`px-3 py-3 rounded-md text-base font-medium transition-colors ${
                        isActive
                          ? "bg-blue-100 text-blue-900"
                          : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                      }`}
                    >
                      {tab.name}
                    </Link>
                  )
                })}
              </nav>
              
              <div className="pt-4 mt-4 border-t px-2">
                <Button 
                  variant="outline" 
                  onClick={handleLogout} 
                  disabled={isLoggingOut}
                  className="w-full justify-start text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700"
                >
                  <LogOut className="w-4 h-4 mr-2" />
                  {isLoggingOut ? "Cerrando sesión..." : "Cerrar sesión"}
                </Button>
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Área de Contenido con Scroll Independiente */}
      <main className="flex-1 overflow-y-auto w-full">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {children}
        </div>
      </main>
    </div>
  )
}