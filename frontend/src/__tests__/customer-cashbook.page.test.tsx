import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import CustomerCashbookPage from "@/app/(dashboard)/manager/financial/customer-cashbook/page";
import { cashReport } from "../../test-utils/customer-cashbook-fixtures";
import { customerCashbookService } from "@/services/customer-cashbook.service";
import { downloadCSV } from "@/lib/csv-export";
const mockReplace = jest.fn();
let mockRole = "AUDITOR";
let mockCurrent = true;
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    isAuthenticated: true,
    user: { id: "staff", role: mockRole },
  }),
}));
jest.mock("@/lib/auth-session", () => ({
  getCredentialGeneration: () => 0,
  onCredentialsChanged: () => () => {},
}));
jest.mock("@/lib/private-task", () => ({
  capturePrivateTask: () => ({
    assertCurrent: () => {
      if (!mockCurrent) throw new Error("session");
    },
    isCurrent: () => mockCurrent,
  }),
}));
jest.mock("@/services/customer-cashbook.service", () => ({
  customerCashbookService: { report: jest.fn() },
}));
jest.mock("@/lib/csv-export", () => ({ downloadCSV: jest.fn() }));
beforeEach(() => {
  jest.resetAllMocks();
  mockRole = "AUDITOR";
  mockCurrent = true;
  (customerCashbookService.report as jest.Mock).mockResolvedValue(cashReport());
});
it("allows auditor read access, exports all loaded rows and clears results on filter edits", async () => {
  render(<CustomerCashbookPage />);
  await screen.findByRole("region", { name: "Libro confirmado" });
  fireEvent.click(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  );
  expect(downloadCSV).toHaveBeenCalledWith(
    expect.arrayContaining([
      expect.objectContaining({ kind: "COBRO" }),
      expect.objectContaining({ kind: "DEVOLUCION" }),
    ]),
    expect.any(String),
  );
  fireEvent.change(screen.getByLabelText("Moneda recibida", { exact: true }), {
    target: { value: "VES" },
  });
  expect(
    screen.queryByRole("region", { name: "Libro confirmado" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Aplicar consulta" }));
  await screen.findByRole("region", { name: "Libro confirmado" });
  expect(customerCashbookService.report).toHaveBeenLastCalledWith({
    date_from: "2026-11-14",
    date_to: "2026-11-14",
    currency: "VES",
    method: undefined,
    source_key: undefined,
  });
});
it("distinguishes a failed request from a confirmed empty report", async () => {
  (customerCashbookService.report as jest.Mock).mockRejectedValueOnce(
    new Error("Servicio temporalmente no disponible"),
  );
  render(<CustomerCashbookPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Servicio temporalmente no disponible",
  );
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeDisabled();
  (customerCashbookService.report as jest.Mock).mockResolvedValue(
    cashReport([]),
  );
  fireEvent.click(screen.getByRole("button", { name: "Aplicar consulta" }));
  await screen.findByText("No hay movimientos verificados para estos filtros.");
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeEnabled();
});
it("does not restore an old request after filters are edited", async () => {
  let resolve!: (v: ReturnType<typeof cashReport>) => void;
  (customerCashbookService.report as jest.Mock).mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  render(<CustomerCashbookPage />);
  fireEvent.change(screen.getByLabelText("Caja o cuenta", { exact: true }), {
    target: { value: "CAJA NUEVA" },
  });
  await act(async () => {
    resolve(cashReport());
  });
  expect(
    screen.queryByRole("region", { name: "Libro confirmado" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeDisabled();
});
it("rejects an operator before requesting private financial data", async () => {
  mockRole = "OPERADOR";
  render(<CustomerCashbookPage />);
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/login"));
  expect(customerCashbookService.report).not.toHaveBeenCalled();
});

it("shows the server guidance when a range cannot be exported completely", async () => {
  (customerCashbookService.report as jest.Mock).mockRejectedValue({
    response: {
      status: 409,
      data: { detail: "El rango supera 5000 movimientos; reduce las fechas" },
    },
  });
  render(<CustomerCashbookPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "reduce las fechas",
  );
  expect(
    screen.getByRole("button", { name: "Exportar CSV completo" }),
  ).toBeDisabled();
});
