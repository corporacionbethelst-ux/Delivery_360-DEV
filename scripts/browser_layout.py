"""Browser geometry checks that also detect clipping by overflow ancestors."""


def assert_order_controls(page):
    """Check complete controls, their clipping ancestors and hit targets."""
    controls = [
        page.get_by_role("group", name="Acciones de órdenes", exact=True).get_by_role(
            "button", name=name, exact=True
        )
        for name in ("Actualizar", "Exportar", "Nueva Orden")
    ] + [
        page.get_by_role("textbox", name="Buscar órdenes", exact=True),
        page.get_by_role("combobox", name="Estado de la orden", exact=True),
        page.get_by_role("combobox", name="Repartidor asignado", exact=True),
    ]
    for index, control in enumerate(controls):
        control.wait_for(state="visible")
        control.evaluate(
            """el => {
                const positions = [];
                for (let p = el.parentElement; p; p = p.parentElement)
                    positions.push([p, p.scrollLeft]);
                const x = scrollX, r = el.getBoundingClientRect();
                if (r.top < 0 || r.bottom > innerHeight)
                    el.scrollIntoView({block:'center', inline:'nearest', behavior:'instant'});
                for (const [p, left] of positions) p.scrollLeft = left;
                window.scrollTo({left:x, top:scrollY, behavior:'instant'});
            }"""
        )
        assert control.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                if (r.width < 40 || r.height < 40 || r.left < -1 ||
                    r.right > innerWidth + 1 || r.top < -1 ||
                    r.bottom > innerHeight + 1) return false;
                for (let p = el.parentElement; p; p = p.parentElement) {
                    const s = getComputedStyle(p), b = p.getBoundingClientRect();
                    if (/(hidden|clip|auto|scroll)/.test(s.overflowX) &&
                        (r.left < b.left - 1 || r.right > b.right + 1)) return false;
                    if (/(hidden|clip|auto|scroll)/.test(s.overflowY) &&
                        (r.top < b.top - 1 || r.bottom > b.bottom + 1)) return false;
                }
                if (el.disabled) return true;
                return [[r.left + 3, (r.top+r.bottom)/2], [r.right - 3, (r.top+r.bottom)/2],
                        [(r.left+r.right)/2, (r.top+r.bottom)/2]].every(([x,y]) => {
                    const hit = document.elementFromPoint(x,y);
                    return hit === el || el.contains(hit);
                });
            }"""
        ), ("Order control %d is clipped, covered, or outside the viewport" % index)
