import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import CurrencyPage from "@/app/(dashboard)/manager/admin/currency/page";
import { currencyService } from "@/services/currency.service";
import {
  context,
  rate,
  quote,
  nextId,
} from "../../test-utils/currency-fixtures";
jest.mock("@/components/layout/ManagerPageBoundary", () => ({
  ManagerPageBoundary: ({ children }: any) => children,
}));
let mockRole = "SUPERADMIN";
jest.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({ user: { role: mockRole } }),
}));
jest.mock("@/services/currency.service", () => ({
  currencyService: {
    context: jest.fn(),
    saveRate: jest.fn(),
    quote: jest.fn(),
    receipt: jest.fn(),
  },
}));
const load = jest.mocked(currencyService.context),
  save = jest.mocked(currencyService.saveRate),
  convert = jest.mocked(currencyService.quote);
const descriptor = Object.getOwnPropertyDescriptor(window.crypto, "randomUUID");
beforeEach(() => {
  jest.resetAllMocks();
  mockRole = "SUPERADMIN";
  window.history.replaceState(null, "", "/manager/admin/currency");
  Object.defineProperty(window.crypto, "randomUUID", {
    configurable: true,
    value: () => nextId,
  });
  load.mockResolvedValue(context);
  save.mockResolvedValue(rate);
  convert.mockResolvedValue(quote);
});
afterEach(() => {
  if (descriptor)
    Object.defineProperty(window.crypto, "randomUUID", descriptor);
  else delete (window.crypto as any).randomUUID;
});
it("blocks quotation when today has no manually verified reference", async () => {
  load.mockResolvedValue({ ...context, current_rate: null, rates: [] });
  render(<CurrencyPage />);
  expect(
    await screen.findByText(/Falta una referencia registrada/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Guardar cotización" }),
  ).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
  expect(convert).not.toHaveBeenCalled();
});
it("requires explicit review and allows cancellation without a write", async () => {
  render(<CurrencyPage />);
  await screen.findByRole("region", { name: "Referencia del día consultado" });
  fireEvent.change(screen.getByLabelText("Bolívares por 1 USD"), {
    target: { value: "1,5" },
  });
  fireEvent.change(screen.getByLabelText("Nota de verificación"), {
    target: { value: rate.note },
  });
  expect(screen.getByRole("button", { name: "Revisar tasa" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Revisar tasa" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Confirmar referencia BCV",
  });
  expect(within(dialog).getByText("1,5")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));
  expect(save).not.toHaveBeenCalled();
});
it("keeps the exact saved quote when the current rate is corrected", async () => {
  render(<CurrencyPage />);
  await screen.findByRole("region", { name: "Referencia del día consultado" });
  fireEvent.change(screen.getByLabelText("Importe en USD"), {
    target: { value: "0,01" },
  });
  fireEvent.change(screen.getByLabelText("Referencia de la cotización"), {
    target: { value: quote.reference },
  });
  fireEvent.click(screen.getByRole("button", { name: "Guardar cotización" }));
  const receipt = await screen.findByRole("region", {
    name: "Cotización conservada",
  });
  expect(within(receipt).getByText("Bs. 0,02")).toBeInTheDocument();
  load.mockResolvedValue({
    ...context,
    current_rate: {
      ...rate,
      id: nextId,
      previous_rate_id: rate.id,
      revision: 2,
      ves_per_usd: "2.50000000",
    },
    rates: [
      {
        ...rate,
        id: nextId,
        previous_rate_id: rate.id,
        revision: 2,
        ves_per_usd: "2.50000000",
      },
      rate,
    ],
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Actualizar referencias" }),
  );
  await screen.findByText("1 USD = 2,50000000 Bs.");
  expect(within(receipt).getByText("Bs. 0,02")).toBeInTheDocument();
  expect(convert).toHaveBeenCalledTimes(1);
});
it("lets an operator quote but hides reference mutation controls", async () => {
  mockRole = "OPERADOR";
  render(<CurrencyPage />);
  await screen.findByText(/Solo gerencia/);
  expect(
    screen.queryByRole("button", { name: "Revisar tasa" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Guardar cotización" }),
  ).toBeEnabled();
});
it("recovers a persisted receipt through its authenticated URL", async () => {
  window.history.replaceState(null, "", "?quote=" + quote.id);
  jest.mocked(currencyService.receipt).mockResolvedValue(quote);
  render(<CurrencyPage />);
  expect(
    await screen.findByRole("region", { name: "Cotización conservada" }),
  ).toHaveTextContent("Bs. 0,02");
  expect(currencyService.receipt).toHaveBeenCalledWith(quote.id);
});

it("retries an uncertain rate write with the same reviewed request", async () => {
  load
    .mockResolvedValueOnce({ ...context, current_rate: null, rates: [] })
    .mockResolvedValue(context);
  save
    .mockRejectedValueOnce(new Error("Respuesta interrumpida"))
    .mockResolvedValue(rate);
  render(<CurrencyPage />);
  await screen.findByText(/Falta una referencia registrada/);
  fireEvent.change(screen.getByLabelText("Bolívares por 1 USD"), {
    target: { value: "1,5" },
  });
  fireEvent.change(screen.getByLabelText("Nota de verificación"), {
    target: { value: rate.note },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Revisar tasa" }));
  let dialog = await screen.findByRole("dialog", {
    name: "Confirmar referencia BCV",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Confirmar tasa" }),
  );
  await within(dialog).findByText("Respuesta interrumpida");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Confirmar tasa" }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(save).toHaveBeenCalledTimes(2);
  expect(save.mock.calls[0][0]).toEqual(save.mock.calls[1][0]);
  expect(save.mock.calls[0][0]).toMatchObject({
    previous_rate_id: null,
    ves_per_usd: "1.5",
    confirmed_bcv: true,
  });
});
