import '@testing-library/jest-dom';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Page from '@/app/(dashboard)/manager/fleet/riders/[id]/documents/page';
import { riderService } from '@/services/rider.service';
import { toast } from 'sonner';

jest.mock('next/navigation', () => ({ useParams: () => ({ id: '123e4567-e89b-42d3-a456-426614174001' }), useRouter: () => ({ push: jest.fn(), back: jest.fn() }) }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn(), warning: jest.fn() } }));
jest.mock('@/services/rider.service', () => ({ riderService: { getDocuments: jest.fn(), approveDocument: jest.fn(), rejectDocument: jest.fn(), deleteDocument: jest.fn() } }));
const service = jest.mocked(riderService);
const id = '123e4567-e89b-42d3-a456-426614174000';
const revision = 'a'.repeat(64);
const row = { id, type: 'LICENCIA' as const, status: 'PENDIENTE' as const, file_url: `/api/v1/riders/documents/${id}/download`, created_at: '2026-10-24T12:00:00', revision };

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(window, 'confirm').mockReturnValue(true);
  service.getDocuments.mockResolvedValue([row]);
});
afterEach(() => jest.restoreAllMocks());

it('approves the snapshot displayed when the action starts', async () => {
  service.approveDocument.mockResolvedValueOnce({ message: 'OK', doc_id: id, status: 'APROBADO', revision: 'b'.repeat(64) });
  render(<Page />);
  fireEvent.click(await screen.findByRole('button', { name: /Aprobar/i }));
  await waitFor(() => expect(service.approveDocument).toHaveBeenCalledWith(id, revision));
  await waitFor(() => expect(toast.success).toHaveBeenCalled());
});

it('refreshes after a stale approval without automatically approving the new revision', async () => {
  service.approveDocument.mockRejectedValueOnce(Object.assign(new Error('El documento cambió'), { status: 409 }));
  render(<Page />);
  fireEvent.click(await screen.findByRole('button', { name: /Aprobar/i }));
  await waitFor(() => expect(service.getDocuments).toHaveBeenCalledTimes(2));
  expect(service.approveDocument).toHaveBeenCalledTimes(1);
  expect(toast.error).toHaveBeenCalledWith('El documento cambió');
});

it('captures the rejection revision before a background refresh changes metadata', async () => {
  service.rejectDocument.mockRejectedValueOnce(Object.assign(new Error('El documento cambió'), { status: 409 }));
  render(<Page />);
  fireEvent.click(await screen.findByRole('button', { name: /^Rechazar$/i }));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  service.getDocuments.mockResolvedValue([{ ...row, revision: 'b'.repeat(64) }]);
  fireEvent.click(screen.getByText(/Actualizar/));
  await waitFor(() => expect(service.getDocuments).toHaveBeenCalledTimes(2));
  fireEvent.click(await screen.findByRole('button', { name: /^Confirmar$/i }));
  await waitFor(() => expect(service.rejectDocument).toHaveBeenCalledWith(id, expect.any(String), revision));
  expect(service.rejectDocument).toHaveBeenCalledTimes(1);
});

it('passes the displayed revision when deleting', async () => {
  service.deleteDocument.mockResolvedValueOnce(undefined);
  render(<Page />);
  fireEvent.click(await screen.findByTitle('Eliminar documento'));
  await waitFor(() => expect(service.deleteDocument).toHaveBeenCalledWith(id, revision));
});

it('refuses a write when old metadata has no revision', async () => {
  service.getDocuments.mockResolvedValue([{ ...row, revision: undefined }]);
  render(<Page />);
  fireEvent.click(await screen.findByRole('button', { name: /Aprobar/i }));
  expect(service.approveDocument).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Recarga'));
});
