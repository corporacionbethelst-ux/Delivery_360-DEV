"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useAuthStore } from "@/stores/authStore"
import { LogOut, User as UserIcon, Menu, X, Bike, LayoutDashboard, Package, DollarSign, TrendingUp, UserCircle } from "lucide-react"
import { authService } from "@/services/auth.service"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

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
    { id: "dashboard", name: "Dashboard", href: "/rider", icon: LayoutDashboard },
    { id: "orders", name: "Órdenes", href: "/rider/my-orders", icon: Package },
    { id: "earnings", name: "Ganancias", href: "/rider/earnings", icon: DollarSign },
    { id: "productivity", name: "Productividad", href: "/rider/productivity", icon: TrendingUp },
    { id: "profile", name: "Perfil", href: "/rider/profile", icon: UserCircle },
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
    <div className="flex flex-col h-screen bg-gray-50 overflow-hidden">
      
      {/* HEADER: z-40 es suficiente ya que el Toaster tiene z-9999 */}
      <header className="bg-white border-b shadow-sm z-40 shrink-0 h-14 sm:h-16 relative">
        <div className="max-w-7xl mx-auto px-2 sm:px-4 lg:px-8 h-full">
          <div className="flex items-center justify-between h-full gap-4">
            
            {/* IZQUIERDA: Logo + Navegación */}
            <div className="flex items-center gap-2 sm:gap-4 lg:gap-6 overflow-hidden">
              <Link href="/rider" className="flex items-center gap-2 shrink-0">
                <div className="w-8 h-8 sm:w-9 sm:h-9 bg-blue-600 rounded-lg flex items-center justify-center text-white shadow-sm hover:bg-blue-700 transition-colors">
                  <Bike className="w-5 h-5" />
                </div>
                <span className="font-bold text-blue-900 hidden md:block text-sm lg:text-base truncate">
                  Delivery360
                </span>
              </Link>

              <div className="hidden md:block w-px h-6 bg-gray-200"></div>

              <nav className="hidden md:flex items-center gap-1">
                {tabs.map((tab) => {
                  const Icon = tab.icon
                  const isActive = pathname === tab.href || (tab.href !== "/rider" && pathname.startsWith(tab.href + "/"))
                  
                  return (
                    <TooltipProvider key={tab.id}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Link
                            href={tab.href}
                            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 whitespace-nowrap ${
                              isActive
                                ? "bg-blue-50 text-blue-700 ring-1 ring-blue-200 shadow-sm"
                                : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                            }`}
                          >
                            <Icon className={`w-4 h-4 ${isActive ? 'text-blue-600' : 'text-gray-400'}`} />
                            <span className="hidden lg:inline">{tab.name}</span>
                          </Link>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" className="md:hidden lg:hidden">
                          <p>{tab.name}</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  )
                })}
              </nav>
            </div>

            {/* DERECHA: Perfil + Logout + Menú Móvil */}
            <div className="flex items-center gap-2 sm:gap-3 shrink-0">
              
              <div className="hidden lg:flex items-center gap-2 pr-3 border-r border-gray-200">
                <div className="text-right">
                  <p className="text-xs font-bold text-gray-900 leading-none truncate max-w-[120px]">
                    {user.first_name} {user.last_name}
                  </p>
                  <Badge variant="outline" className="text-[9px] h-4 px-1 mt-1 border-gray-200 text-gray-500 font-normal">
                    Repartidor
                  </Badge>
                </div>
                <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold text-xs border border-blue-200">
                  {user.first_name.charAt(0)}{user.last_name.charAt(0)}
                </div>
              </div>

              <button
                onClick={handleLogout}
                disabled={isLoggingOut}
                className="hidden lg:flex items-center justify-center w-9 h-9 text-red-500 hover:bg-red-50 rounded-md transition-colors disabled:opacity-50"
                title="Cerrar sesión"
              >
                <LogOut className="w-5 h-5" />
              </button>

              <button 
                className="lg:hidden p-2 text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                aria-label="Toggle menu"
              >
                {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              </button>
            </div>
          </div>
        </div>

        {/* MENÚ MÓVIL */}
        {mobileMenuOpen && (
          <div className="lg:hidden absolute top-14 left-0 right-0 bg-white border-b shadow-xl animate-in slide-in-from-top-2 z-50">
            <div className="p-4 space-y-2">
              <div className="flex items-center gap-3 mb-4 p-3 bg-gray-50 rounded-lg border border-gray-100">
                <div className="w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
                  {user.first_name.charAt(0)}{user.last_name.charAt(0)}
                </div>
                <div>
                  <p className="font-bold text-gray-900 text-sm">{user.first_name} {user.last_name}</p>
                  <p className="text-xs text-gray-500">{user.email}</p>
                </div>
              </div>
              
              <nav className="grid gap-1">
                {tabs.map((tab) => {
                  const Icon = tab.icon
                  const isActive = pathname === tab.href || (tab.href !== "/rider" && pathname.startsWith(tab.href + "/"))
                  return (
                    <Link
                      key={tab.id}
                      href={tab.href}
                      onClick={() => setMobileMenuOpen(false)}
                      className={`flex items-center gap-3 px-3 py-3 rounded-lg text-sm font-medium transition-colors ${
                        isActive
                          ? "bg-blue-50 text-blue-700 border border-blue-100"
                          : "text-gray-600 hover:bg-gray-50"
                      }`}
                    >
                      <Icon className={`w-5 h-5 ${isActive ? 'text-blue-600' : 'text-gray-400'}`} />
                      {tab.name}
                    </Link>
                  )
                })}
              </nav>
              
              <div className="pt-4 mt-4 border-t border-gray-100">
                <Button 
                  variant="outline" 
                  onClick={() => {
                    setMobileMenuOpen(false)
                    handleLogout()
                  }} 
                  disabled={isLoggingOut}
                  className="w-full justify-start text-red-600 border-red-200 hover:bg-red-50 bg-white"
                >
                  <LogOut className="w-4 h-4 mr-2" />
                  Cerrar sesión
                </Button>
              </div>
            </div>
          </div>
        )}
      </header>

      <main className="flex-1 overflow-y-auto w-full scroll-smooth bg-gray-50 relative z-0">
        <div className="max-w-7xl mx-auto px-2 sm:px-4 lg:px-8 py-6">
          {children}
        </div>
      </main>
    </div>
  )
}