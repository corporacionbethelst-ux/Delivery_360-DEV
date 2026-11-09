import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import Canvas from "@/app/(dashboard)/manager/fleet/riders/map/RiderMapCanvas";
import type { RiderMapPoint } from "@/lib/rider-map";

const mockMap = {
  fitBounds: jest.fn(),
  setView: jest.fn(),
  invalidateSize: jest.fn(),
  getContainer: () => document.body,
};
const mockTileMount = jest.fn();
let mockTileHandlers: { tileerror: () => void }, mockResize: () => void;
const mockObserve = jest.fn(),
  mockDisconnect = jest.fn();
jest.mock("leaflet", () => ({
  __esModule: true,
  default: {
    divIcon: (options: any) => options,
    latLngBounds: (points: any) => points,
  },
}));
jest.mock("react-leaflet", () => ({
  MapContainer: ({ children }: any) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  useMap: () => mockMap,
  TileLayer: ({ eventHandlers }: any) => {
    mockTileHandlers = eventHandlers;
    require("react").useEffect(() => {
      mockTileMount();
    }, []);
    return <div />;
  },
  Marker: ({ children, position, icon, title }: any) => (
    <div
      data-testid="marker"
      data-lat={position[0]}
      data-lng={position[1]}
      data-icon={icon.html}
      title={title}
    >
      {children}
    </div>
  ),
  Popup: ({ children }: any) => <div>{children}</div>,
}));
const points: RiderMapPoint[] = [
  {
    rider: {
      id: "rider/a",
      first_name: "José",
      last_name: "Pérez",
      is_online: false,
      phone: "+58 (412) 123-4567",
      vehicle_type: "MOTO",
    },
    position: [0, 0],
  },
];
beforeEach(() => {
  jest.clearAllMocks();
  global.ResizeObserver = class {
    constructor(callback: ResizeObserverCallback) {
      mockResize = () => callback([], this);
    }
    observe = mockObserve;
    unobserve = jest.fn();
    disconnect = mockDisconnect;
  };
});
it("mantiene el marcador en cero y descarga iconos locales sin incorporar nombres al HTML", () => {
  render(<Canvas points={points} focus={null} fitSequence={0} />);
  expect(screen.getByTestId("marker")).toHaveAttribute("data-lat", "0");
  expect(screen.getByTestId("marker")).toHaveAttribute("data-lng", "0");
  expect(screen.getByTestId("marker").getAttribute("data-icon")).not.toContain(
    "José",
  );
  expect(mockMap.fitBounds).toHaveBeenCalledWith([[0, 0]], {
    padding: [35, 35],
    maxZoom: 14,
    animate: false,
  });
});
it("centra explícitamente sin animación y una lectura nueva no deshace la vista elegida", () => {
  const focus = { position: [0, 0] as [number, number], sequence: 1 };
  const view = render(<Canvas points={points} focus={focus} fitSequence={0} />);
  expect(mockMap.setView).toHaveBeenCalledWith([0, 0], 15, { animate: false });
  view.rerender(
    <Canvas
      points={[{ ...points[0], position: [1, 2] }]}
      focus={focus}
      fitSequence={0}
    />,
  );
  expect(mockMap.fitBounds).toHaveBeenCalledTimes(1);
  expect(mockMap.setView).toHaveBeenCalledTimes(1);
});
it("ajustar a puntos actualizados vuelve a encuadrar sus coordenadas", () => {
  const view = render(<Canvas points={points} focus={null} fitSequence={0} />);
  view.rerender(
    <Canvas
      points={[{ ...points[0], position: [10, -66] }]}
      focus={null}
      fitSequence={1}
    />,
  );
  expect(mockMap.fitBounds).toHaveBeenLastCalledWith(
    [[10, -66]],
    expect.objectContaining({ animate: false }),
  );
  expect(mockMap.fitBounds).toHaveBeenCalledTimes(2);
});
it("sin puntos muestra la referencia mundial y el primer resultado válido se encuadra", () => {
  const view = render(<Canvas points={[]} focus={null} fitSequence={0} />);
  expect(mockMap.setView).toHaveBeenCalledWith([0, 0], 2, { animate: false });
  expect(screen.queryByTestId("marker")).not.toBeInTheDocument();
  view.rerender(<Canvas points={points} focus={null} fitSequence={0} />);
  expect(mockMap.fitBounds).toHaveBeenCalledTimes(1);
  view.rerender(<Canvas points={[]} focus={null} fitSequence={1} />);
  expect(mockMap.setView).toHaveBeenLastCalledWith([0, 0], 2, {
    animate: false,
  });
});
it("el popup ofrece perfil y llamada reales, sin un botón de contacto inerte", () => {
  render(<Canvas points={points} focus={null} fitSequence={0} />);
  expect(screen.getByRole("link", { name: "Ver perfil" })).toHaveAttribute(
    "href",
    "/manager/fleet/riders/rider%2Fa",
  );
  expect(
    screen.getByRole("link", { name: "Llamar a José Pérez" }),
  ).toHaveAttribute("href", "tel:+584121234567");
  expect(screen.getByText("Desconectado")).toBeVisible();
  expect(screen.getByText("Estado: No informado")).toBeVisible();
  expect(screen.getByText("Email no informado")).toBeVisible();
  expect(screen.getByText(/Reportada: Fecha no informada/)).toBeVisible();
});
it("un teléfono no utilizable y conexión desconocida no inventan una llamada o desconexión", () => {
  render(
    <Canvas
      points={[
        {
          ...points[0],
          rider: {
            ...points[0].rider,
            phone: "javascript:call()",
            is_online: undefined,
          },
        },
      ]}
      focus={null}
      fitSequence={0}
    />,
  );
  expect(
    screen.queryByRole("link", { name: /Llamar/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Disponibilidad no informada")).toBeVisible();
});
it("el fallo de teselas avisa sin ocultar puntos y reintentar recrea la capa", () => {
  render(<Canvas points={points} focus={null} fitSequence={0} />);
  act(() => mockTileHandlers.tileerror());
  expect(screen.getByRole("alert")).toHaveTextContent("fondo cartográfico");
  expect(screen.getByTestId("marker")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar fondo del mapa" }),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(mockTileMount).toHaveBeenCalledTimes(2);
});
it("los cambios de tamaño invalidan el lienzo y desmontar retira el observador", () => {
  const view = render(<Canvas points={points} focus={null} fitSequence={0} />);
  expect(mockObserve).toHaveBeenCalledWith(document.body);
  act(() => mockResize());
  expect(mockMap.invalidateSize).toHaveBeenCalledWith({ pan: false });
  view.unmount();
  expect(mockDisconnect).toHaveBeenCalledTimes(1);
});
