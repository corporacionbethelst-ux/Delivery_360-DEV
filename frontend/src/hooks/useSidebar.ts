'use client';

import { useState, useEffect } from 'react';

export function useSidebar() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
    // Detectar móvil
    const checkMobile = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (mobile) {
        setIsCollapsed(true); // En móvil siempre empieza cerrado (offcanvas)
      } else {
        // En desktop, recuperar preferencia guardada
        let saved: string|null = null;
        try { saved = localStorage.getItem('sidebar-collapsed'); } catch { /* Optional display preference. */ }
        setIsCollapsed(saved === 'true');
      }
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  const toggle = () => {
    setIsCollapsed(previous => {
      const next = !previous;
      if (!isMobile) { try { localStorage.setItem('sidebar-collapsed',String(next)); } catch { /* Storage denial must not block navigation. */ } }
      return next;
    });
  };

  return { isCollapsed, isMobile, toggle, isMounted };
}
